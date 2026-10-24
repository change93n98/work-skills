import sqlite3
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from kernel_categories import KernelClassifier
from prof import analyze_window, classify_rows, read_xlsx, resolve_trace, us_to_ns, window_queries


class SqlProcessor:
    def __init__(self, connection):
        self.connection=connection

    def query(self, sql):
        cursor=self.connection.execute(sql)
        columns=[c[0] for c in cursor.description]
        values=cursor.fetchall()
        return Rows(columns,values)


class Rows:
    def __init__(self, columns, values):
        self.column_names=columns
        self.values=values

    def __iter__(self):
        return iter(types.SimpleNamespace(**dict(zip(self.column_names,v))) for v in self.values)


class ExplicitWindowTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.base=1792745261566929000
        self.db.executescript('CREATE TABLE trace_bounds(start_ts INTEGER,end_ts INTEGER);'
                             'CREATE TABLE slice(name TEXT, ts INTEGER, dur INTEGER, category TEXT, track_id INTEGER);')
        self.db.execute('INSERT INTO trace_bounds VALUES(?,?)',(self.base,self.base+1000000))
        self.tp=SqlProcessor(self.db)

    def insert(self, name, ts, dur, cat='kernel', track=3):
        self.db.execute('INSERT INTO slice VALUES(?,?,?,?,?)',(name,self.base+ts,dur,cat,track))

    def test_microsecond_precision_and_invalid_values(self):
        self.assertEqual(us_to_ns('34860750.232'),34860750232)
        self.assertEqual(us_to_ns('0.001'),1)
        for bad in ('NaN','Infinity','-1','0.0001','hello'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):us_to_ns(bad)

    def test_exact_epoch_boundary_selection_and_full_duration(self):
        self.insert('before',9999,100000)
        self.insert('teco_slave_gemm(Args)',10000,2000)
        self.insert('cross_end',19999,5000)
        self.insert('end',20000,1000)
        self.insert('host',15000,3000,'cpu_op')
        rows,meta,sql=analyze_window(self.tp,'10','20')
        self.assertEqual({r['name'] for r in rows},{'teco_slave_gemm(Args)','cross_end'})
        self.assertEqual(sum(r['total_duration_us'] for r in rows),7)
        self.assertEqual(meta['events_crossing_end'],1)
        self.assertEqual(meta['absolute_start_ts_ns'],str(self.base+10000))
        self.assertEqual(sum(r['window_absolute_pct'] for r in rows),70)

    def test_sql_raw_percent_keeps_wait_category_percent_excludes_it(self):
        self.insert('teco_slave_gemm(Args)',10000,1000)
        self.insert('WAIT',11000,3000,'gpu_memset')
        self.insert('SET',12000,0,'gpu_memset')
        raw,_,_=analyze_window(self.tp,'10','20')
        self.assertEqual(next(r for r in raw if r['name'].startswith('teco'))['kernel_relative_pct'],25)
        rows,summary,excluded,busy=classify_rows(raw,KernelClassifier(platform='teco'))
        self.assertEqual(busy,1)
        self.assertEqual(excluded['total_duration_us'],3)
        self.assertEqual(summary[0]['kernel_relative_pct'],100)
        self.assertEqual(len(rows),3)

    def test_custom_device_categories_and_track_scope(self):
        self.insert('a',10000,1000,'kernel',3)
        self.insert('b',11000,1000,'sdaa_kernel',4)
        rows,_,_=analyze_window(self.tp,'10','20',('kernel','sdaa_kernel'),[4])
        self.assertEqual([r['name'] for r in rows],['b'])
        with self.assertRaises(ValueError):window_queries(0,10,('kernel','cpu_op'))
        with self.assertRaises(ValueError):window_queries(0,10,('privateuse1_runtime',))

    def test_invalid_range_empty_window_and_unfinished_event(self):
        for start,end in [('20','10'),('0','1001'),('10','20')]:
            with self.subTest(start=start),self.assertRaises(ValueError):analyze_window(self.tp,start,end)
        self.insert('unfinished',10000,-1)
        with self.assertRaises(ValueError):analyze_window(self.tp,'10','20')

    def test_raw_query_matches_supplied_aggregation_and_avg_integer_division(self):
        self.insert('a',10000,1001)
        self.insert('a',11000,1002)
        raw,_,_=analyze_window(self.tp,'10','20')
        self.assertEqual(raw[0]['record_count'],2)
        self.assertEqual(raw[0]['total_duration_us'],2.003)
        self.assertEqual(raw[0]['avg_duration_us'],1.001)
        self.assertEqual(raw[0]['kernel_relative_pct'],100)

    def test_unknown_evidence_zero_compute_and_missing_window(self):
        classifier=KernelClassifier(platform='teco')
        raw=[dict(name='opaque_zeta',record_count=2,total_duration_us=0,window_absolute_pct=None)]
        rows,summary,excluded,busy=classify_rows(raw,classifier)
        self.assertEqual(rows[0]['classification']['confidence'],'unknown')
        self.assertEqual(busy,0)
        self.assertIsNone(summary[0]['kernel_relative_pct'])
        self.assertIsNone(summary[0]['window_absolute_pct'])
        for bad in (-1,float('nan'),None):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                classify_rows([dict(raw[0],total_duration_us=bad)],classifier)

    def test_directory_must_resolve_one_trace(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):resolve_trace(root)
            p=Path(root)/'rank0.json.gz';p.write_bytes(b'fixture')
            self.assertEqual(resolve_trace(root),p)
            (Path(root)/'rank1.json.gz').write_bytes(b'fixture')
            with self.assertRaises(ValueError):resolve_trace(root)

    def test_xlsx_reader_handles_absent_dimension_metadata_and_blanks(self):
        class Sheet:
            title='data'
            max_row=max_column=None  # Valid XLSX produced without <dimension>.
            def iter_rows(self, min_row=1, values_only=False):
                rows=[('name','record_count','total_duration_us','old category'),
                      ('WAIT',2,3,'keep'),(None,None,None,None),('kernel',1,4,'keep')]
                return iter(rows[min_row-1:])
        wb=types.SimpleNamespace(worksheets=[Sheet()],sheetnames=['data'],close=lambda:None)
        with patch('openpyxl.load_workbook',return_value=wb):
            rows,metadata=read_xlsx('fixture.xlsx')
        self.assertEqual([r['source_row'] for r in rows],[2,4])
        self.assertEqual(metadata['source_columns'],4)
        self.assertEqual(metadata['source_row_count'],4)


if __name__=='__main__':unittest.main()
