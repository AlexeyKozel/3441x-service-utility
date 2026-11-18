"""Offline repair contracts with synthetic image content and real binary framing."""
import json
import contextlib
import io
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utility3441x import nor_repair as nr
from utility3441x.offline import KNOWN_APP_DECOMP, KNOWN_REC_DECOMP
from utility3441x.srecord import build_xs


class NorRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data=random.Random(71).randbytes(110000)
        cls.digest=nr.sha256(data)
        cls.z=zlib.compress(data)
        cpu=bytearray(b'\xff'*nr.NOR_SIZE)
        for offset,base in ((0,nr.APP_BASE),(nr.REC_OFFSET,nr.REC_BASE)):
            image=bytearray(0x20000)
            image[0x100:0x100+len(cls.z)]=cls.z
            struct.pack_into('>I',image,4,base+len(image)-1)
            total=sum(struct.unpack('>'+str((len(image)-16)//4)+'I',image[16:]))&0xffffffff
            struct.pack_into('>I',image,0,total)
            cpu[offset:offset+len(image)]=image
        cpu[-4:]=(0x48000002|(nr.REC_BASE&0x3fffffc)).to_bytes(4,'big')
        cls.cpu=bytes(cpu)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for database in (KNOWN_APP_DECOMP,KNOWN_REC_DECOMP):
            p=patch.dict(database,{self.digest:('34411A','2.43')});p.start();self.addCleanup(p.stop)
        self.target=self.file('target.bin',self.cpu)
        self.donor=self.file('donor.bin',self.cpu)
        body=bytes(4924)
        self.cal=self.file('cal.bin',struct.pack('>HII',45,len(body),(~sum(body))&0xffffffff)+body)

    def file(self,name,data):
        p=self.root/name;p.write_bytes(data);return p

    def package(self,kind='app',partial=False):
        start=0 if kind=='app' else nr.REC_OFFSET
        spans=[(nr.NOR_BASE+start,self.cpu[start:start+8])]
        end=start+(0x10000 if partial else 0x20000)
        spans.extend((nr.NOR_BASE+i,self.cpu[i:min(i+32,end)]) for i in range(start+16,end,32))
        return self.file(kind+'.xs',build_xs(model='34411A',image_type='instrumentimage' if kind=='app' else 'updateimage',
                  image_revision='2.43',description='Synthetic test image',s3_records=spans))

    def test_cal_record_and_exclusive_output(self):
        plan=nr.plan_repair(self.target,cal=self.cal)
        self.assertEqual(plan.report['actions'][0]['slot'],'A0')
        self.assertEqual(plan.output[:nr.REGION_OFFSET],self.cpu[:nr.REGION_OFFSET])
        self.assertEqual(plan.output[nr.REGION_OFFSET+nr.REGION_SIZE:],self.cpu[nr.REGION_OFFSET+nr.REGION_SIZE:])
        out=self.root/'new.bin';nr.save_plan(plan,out)
        self.assertEqual(out.read_bytes(),plan.output)
        self.assertEqual(json.loads(Path(str(out)+'.json').read_text())['outsidePlanChangedBytes'],0)
        with self.assertRaises(ValueError):nr.save_plan(plan,out)
        with self.assertRaises(ValueError):nr.save_plan(plan,self.target)
        self.assertEqual(self.target.read_bytes(),self.cpu)

    def test_cal_retires_marker_preserves_body_and_rejects_full(self):
        first=nr.plan_repair(self.target,cal=self.cal)
        self.target.write_bytes(first.output)
        second=nr.plan_repair(self.target,cal=self.cal)
        a=nr.REGION_OFFSET
        self.assertEqual(second.output[a:a+2],b'\0\0')
        self.assertEqual(second.output[a+2:a+nr.SLOT_SIZE],first.output[a+2:a+nr.SLOT_SIZE])
        full=bytearray(first.output);record=first.output[a:a+nr.SLOT_SIZE]
        for i in range(32):full[a+i*nr.SLOT_SIZE:a+(i+1)*nr.SLOT_SIZE]=(b'\0\0'+record[2:]) if i else record
        self.target.write_bytes(full)
        with self.assertRaisesRegex(ValueError,'full'):nr.plan_repair(self.target,cal=self.cal)

    def test_programmer_order_and_trailer(self):
        trailer=b'programmer metadata'
        self.target.write_bytes(nr.swap_pairs(self.cpu)+trailer)
        p=nr.plan_repair(self.target,cal=self.cal)
        self.assertEqual(p.report['inputOrder'],'programmer')
        self.assertEqual(p.output[-len(trailer):],trailer)
        self.assertEqual(nr.normalize(p.output)[0][:nr.REGION_OFFSET],self.cpu[:nr.REGION_OFFSET])

    def test_overwrite_full_and_corrupt_journal(self):
        first=nr.plan_repair(self.target,cal=self.cal)
        a=nr.REGION_OFFSET
        record=first.output[a:a+nr.SLOT_SIZE]
        for label,region in [('full',record*32),('corrupt',b'\x12'*nr.REGION_SIZE)]:
            with self.subTest(label=label):
                damaged=self.cpu[:a]+region+self.cpu[a+nr.REGION_SIZE:]
                self.target.write_bytes(nr.swap_pairs(damaged)+b'trailer')
                plan=nr.plan_repair(self.target,cal=self.cal,overwrite_cal_journal=True)
                cpu,_=nr.normalize(plan.output)
                self.assertEqual(cpu[a:a+nr.SLOT_SIZE],record)
                self.assertEqual(cpu[a+nr.SLOT_SIZE:a+nr.REGION_SIZE],b'\xff'*(nr.REGION_SIZE-nr.SLOT_SIZE))
                self.assertEqual(cpu[:a],damaged[:a])
                self.assertEqual(cpu[a+nr.REGION_SIZE:],damaged[a+nr.REGION_SIZE:])
                self.assertTrue(plan.output.endswith(b'trailer'))
                self.assertEqual(plan.report['actions'][0]['mode'],'overwrite')
                self.assertIn('all previous records removed',nr.summary(plan))
                out=self.root/(label+'.bin');nr.save_plan(plan,out)
                self.assertEqual(self.target.read_bytes(),nr.swap_pairs(damaged)+b'trailer')
                self.assertEqual(out.read_bytes(),plan.output)

    def test_overwrite_requires_valid_source(self):
        with self.assertRaisesRegex(ValueError,'requires a CAL source'):
            nr.plan_repair(self.target,app=self.donor,overwrite_cal_journal=True)
        self.cal.write_bytes(struct.pack('>HII',45,4924,0)+bytes(4924))
        with self.assertRaisesRegex(ValueError,'intact schema45'):
            nr.plan_repair(self.target,cal=self.cal,overwrite_cal_journal=True)
        self.assertEqual(self.target.read_bytes(),self.cpu)

    def test_cli_overwrite(self):
        from utility3441x.cli import main
        self.target.write_bytes(self.cpu[:nr.REGION_OFFSET]+b'\x12'*nr.REGION_SIZE+self.cpu[nr.REGION_OFFSET+nr.REGION_SIZE:])
        out=self.root/'overwrite.bin'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['repair-nor',str(self.target),'--cal',str(self.cal),
                                   '--overwrite-cal-journal','--output',str(out)]),0)
        report=json.loads(Path(str(out)+'.json').read_text())
        self.assertEqual(report['actions'][0]['mode'],'overwrite')

    def test_xs_repairs_app_preserves_uncovered_bytes(self):
        damaged=bytearray(self.cpu);damaged[0x100]^=1;damaged[8:16]=b'RESERVED'
        self.target.write_bytes(damaged)
        p=nr.plan_repair(self.target,app=self.package())
        self.assertTrue(p.report['app']['checksumValid'])
        self.assertEqual(p.output[8:16],b'RESERVED')
        self.assertEqual(p.output[16:],self.cpu[16:])

    def test_recovery_reset_separate_and_partial_package_rejected(self):
        damaged=bytearray(self.cpu);damaged[nr.REC_OFFSET+0x100]^=1;damaged[-4:]=bytes(4)
        self.target.write_bytes(damaged)
        p=nr.plan_repair(self.target,recovery=self.donor,model='34411A',restore_reset=True)
        self.assertEqual(p.output,self.cpu)
        with self.assertRaisesRegex(ValueError,'complete logical image'):
            nr.plan_repair(self.target,recovery=self.package('recovery',True),model='34411A')

    def test_recovery_package_and_standalone(self):
        package=self.package('recovery')
        p=nr.plan_repair(self.target,recovery=package)
        self.assertEqual(p.output,self.cpu)
        with self.assertRaisesRegex(ValueError,'reset vector'):
            nr.plan_repair(self.target,recovery=package,restore_reset=True)
        standalone=self.file('rec.bin',self.cpu[nr.REC_OFFSET:nr.REC_OFFSET+0x20000])
        self.assertEqual(nr.plan_repair(self.target,recovery=standalone).output,self.cpu)

    def test_damaged_headers_explicit_order_model(self):
        damaged=bytearray(self.cpu);damaged[:16]=bytes(16);damaged[nr.REC_OFFSET:nr.REC_OFFSET+16]=bytes(16)
        self.target.write_bytes(damaged)
        with self.assertRaisesRegex(ValueError,'byte order'):nr.plan_repair(self.target,app=self.donor)
        with self.assertRaisesRegex(ValueError,'model'):nr.plan_repair(self.target,app=self.donor,order='cpu')
        p=nr.plan_repair(self.target,app=self.donor,recovery=self.donor,order='cpu',model='34411A')
        self.assertEqual(p.output,self.cpu)

    def test_identity_from_content_not_personality(self):
        # No SA96 writer signature exists anywhere in this synthetic image.
        p=nr.plan_repair(self.target,app=self.donor)
        self.assertEqual(p.report['identityBasis'],'Recovery decompressed content')
        with self.assertRaisesRegex(ValueError,'conflicts'):nr.plan_repair(self.target,app=self.donor,model='34410A')
        with patch.dict(KNOWN_APP_DECOMP,{self.digest:('34410A','2.43')}):
            with self.assertRaisesRegex(ValueError,'does not match'):nr.plan_repair(self.target,app=self.donor)

    def test_source_changed_after_preview(self):
        p=nr.plan_repair(self.target,cal=self.cal)
        self.cal.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):nr.save_plan(p,self.root/'new.bin')
        self.assertFalse((self.root/'new.bin').exists())

    def test_unaligned_header_does_not_break_order_detection(self):
        damaged=bytearray(self.cpu);struct.pack_into('>I',damaged,4,nr.APP_BASE+16)
        self.target.write_bytes(damaged)
        p=nr.plan_repair(self.target,app=self.donor)
        self.assertEqual(p.output,self.cpu)

    def test_invalid_cal_and_ambiguous_journal_rejected(self):
        bad=bytearray(self.cal.read_bytes());bad[-1]^=1;self.cal.write_bytes(bad)
        with self.assertRaisesRegex(ValueError,'intact schema45'):nr.plan_repair(self.target,cal=self.cal)
        damaged=bytearray(self.cpu);damaged[nr.REGION_OFFSET]=0
        self.target.write_bytes(damaged);bad[-1]^=1;self.cal.write_bytes(bad)
        with self.assertRaisesRegex(ValueError,'damaged'):nr.plan_repair(self.target,cal=self.cal)

    def test_cli_preview_and_save_never_open_instrument(self):
        from utility3441x.cli import main
        out=self.root/'cli.bin'
        with patch('utility3441x.cli.VisaInstrument',side_effect=AssertionError('Offline only')):
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(main(['repair-nor',str(self.target),'--cal',str(self.cal)]),0)
            self.assertEqual(json.loads(stream.getvalue())['targetModel'],'34411A')
            self.assertFalse(out.exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['repair-nor',str(self.target),'--app',str(self.donor),'--output',str(out)]),0)
        self.assertEqual(out.read_bytes(),self.cpu)

    def test_protected_cal_package_address_rejected(self):
        raw=build_xs(model='34411A',image_type='instrumentimage',image_revision='2.43',description='Invalid coverage',
                     s3_records=[(nr.NOR_BASE+nr.REGION_OFFSET,b'bad')])
        with self.assertRaisesRegex(ValueError,'protected'):
            nr.plan_repair(self.target,app=self.file('bad.xs',raw))

    def test_gui_controls_and_preview_route(self):
        import tkinter as tk
        from utility3441x.nor_repair_viewer import NorRepairViewer
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        calls=[]
        root._run_worker=lambda label,job:calls.append(job())
        view=NorRepairViewer(root);view.withdraw()
        view.fields['target'].set(str(self.target));view.fields['cal'].set(str(self.cal))
        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)
        preview=next(w for w in children(view) if w.winfo_class()=='TButton' and w.cget('text')=='Preview in main log')
        preview.invoke();root.update_idletasks()
        self.assertIn('Recovery decompressed content',calls[0])
        self.assertFalse(view.reset.get())
        self.assertFalse(view.overwrite_cal.get())
        view.overwrite_cal.set(True)
        preview.invoke()
        self.assertIn('Overwrite CAL journal',calls[-1])


if __name__=='__main__': unittest.main()
