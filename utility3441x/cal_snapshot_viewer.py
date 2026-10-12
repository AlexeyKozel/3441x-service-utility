"""Offline comparison of dated CAL backups, with per-instrument time plots."""
from datetime import datetime, timezone
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog

from .cal_snapshots import ordered_snapshots, default_reference, snapshot_trend
from .cal_engine import comparison_rows
from .cal_engine import coefficient_choices


class CalSnapshotViewer(tk.Toplevel):
    def __init__(self, parent, snapshots):
        super().__init__(parent)
        self.title('Compare CAL backups')
        self.geometry('1220x840')
        self.minsize(960, 650)
        self.snapshots = ordered_snapshots(snapshots)
        self.by_id = {s['id']: s for s in self.snapshots}
        ttk.Label(self, text='Saved snapshots; dates are backup dates, not calibration dates. Changes do not establish instrument drift.', padding=8).pack(anchor='w')
        top = ttk.Frame(self, padding=8); top.pack(fill='x')
        self.files = ttk.Treeview(top, columns=('file','serial','date','source'), show='headings', height=5, selectmode='browse')
        for key, title, width in [('file','File',450),('serial','Serial',145),('date','Saved at (UTC)',215),('source','Date source',130)]:
            self.files.heading(key,text=title); self.files.column(key,width=width)
        self.files.pack(side='left',fill='x',expand=True)
        scroll=ttk.Scrollbar(top,command=self.files.yview);scroll.pack(side='left',fill='y');self.files.configure(yscrollcommand=scroll.set)
        actions=ttk.Frame(top);actions.pack(side='right',padx=8)
        ttk.Button(actions,text='Set as reference',command=self.set_reference).pack(fill='x',pady=2)
        ttk.Button(actions,text='Use earliest reference',command=self.earliest).pack(fill='x',pady=2)
        ttk.Button(actions,text='Set date for this session…',command=self.set_date).pack(fill='x',pady=2)
        self.reference = default_reference(self.snapshots)['id']
        self.target = next((s['id'] for s in reversed(self.snapshots) if s['serial']==self.by_id[self.reference]['serial']),self.reference)
        self.summary=ttk.Label(self,wraplength=1160,padding=(8,0));self.summary.pack(fill='x')
        self.details=ttk.Label(self,wraplength=1160,padding=8);self.details.pack(fill='x')
        tabs=ttk.Notebook(self);tabs.pack(fill='both',expand=True,padx=8,pady=8)
        changes=ttk.Frame(tabs,padding=8);plot=ttk.Frame(tabs,padding=8)
        tabs.add(changes,text='Changes');tabs.add(plot,text='Changes over time')
        bar=ttk.Frame(changes);bar.pack(fill='x')
        self.search=tk.StringVar(); self.family=tk.StringVar(value='All');self.only=tk.BooleanVar(value=True);self.technical=tk.BooleanVar(value=False)
        ttk.Label(bar,text='Search').pack(side='left');ttk.Entry(bar,textvariable=self.search,width=30).pack(side='left',padx=5)
        families=sorted({r.get('meaning',{}).get('family','') for r in self.snapshots[0]['report']['schema45']['values']})
        ttk.Combobox(bar,textvariable=self.family,values=['All']+families,state='readonly',width=20).pack(side='left',padx=5)
        ttk.Checkbutton(bar,text='Only changed',variable=self.only,command=self.refresh).pack(side='left')
        ttk.Checkbutton(bar,text='Technical details',variable=self.technical,command=self.show_detail).pack(side='left',padx=8)
        ttk.Button(bar,text='Export visible rows to CSV…',command=self.export_csv).pack(side='right')
        frame=ttk.Frame(changes);frame.pack(fill='both',expand=True,pady=8);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        self.table=ttk.Treeview(frame,columns=('a','b','delta'),show='tree headings')
        self.table.heading('#0',text='Parameter');self.table.column('#0',width=400)
        for key,title,width in [('a','Reference A',225),('b','Selected B',225),('delta','Change B − A',200)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        self.table.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(frame,command=self.table.yview);scroll.grid(row=0,column=1,sticky='ns');self.table.configure(yscrollcommand=scroll.set)
        scroll=ttk.Scrollbar(frame,orient='horizontal',command=self.table.xview);scroll.grid(row=1,column=0,sticky='ew');self.table.configure(xscrollcommand=scroll.set)
        self.table.tag_configure('changed',background='#fff2ce')
        self.raw=ttk.Label(changes,wraplength=1120);self.raw.pack(fill='x')
        self.choices=coefficient_choices({'slots':self.snapshots});self.choice_map={c['label']:c for c in self.choices}
        self.metric=tk.StringVar(value=self.choices[0]['label'] if self.choices else '')
        ttk.Combobox(plot,textvariable=self.metric,values=list(self.choice_map),state='readonly',width=85).pack(anchor='w')
        self.plot_note=ttk.Label(plot,wraplength=1120);self.plot_note.pack(fill='x',pady=8)
        self.canvas=tk.Canvas(plot,background='white',height=330);self.canvas.pack(fill='both',expand=True)
        ttk.Label(plot,text='Only dated snapshots of the reference instrument are plotted. Equal dates remain separate points; points are not connected.').pack(anchor='w',pady=5)
        self.files.bind('<<TreeviewSelect>>',self.selected)
        self.table.bind('<<TreeviewSelect>>',self.show_detail)
        self.search.trace_add('write',self.refresh);self.family.trace_add('write',self.refresh)
        self.metric.trace_add('write',self.redraw);self.canvas.bind('<Configure>',self.redraw)
        self.populate();self.refresh()

    def populate(self):
        self.snapshots=ordered_snapshots(self.snapshots)
        self.files.delete(*self.files.get_children())
        for s in self.snapshots:
            self.files.insert('', 'end',iid=s['id'],values=(Path(s['path']).name,s['serial'] or 'Unknown',s['date'].isoformat() if s['date'] else 'Unknown',s['dateSource']))
        self.files.selection_set(self.target)

    def selected(self,*_):
        ids=self.files.selection()
        if ids:self.target=ids[0];self.refresh()

    def set_reference(self):
        self.reference=self.target;self.refresh()

    def earliest(self):
        serial=self.by_id[self.target]['serial']
        group=[s for s in self.snapshots if s['serial']==serial] if serial else [self.by_id[self.target]]
        self.reference=default_reference(group)['id'];self.refresh()

    def set_date(self):
        value=simpledialog.askstring('Snapshot date','Enter saved date/time as ISO 8601 with timezone (e.g. 2026-10-09T12:00:00Z).\nThis changes only this session.',parent=self)
        if value is None:return
        try:
            date=datetime.fromisoformat(value.replace('Z','+00:00'))
            if date.tzinfo is None:raise ValueError('Timezone is required.')
            date=date.astimezone(timezone.utc)
        except ValueError as exc:
            messagebox.showerror('Invalid date',str(exc),parent=self);return
        s=self.by_id[self.target];s['date']=date;s['dateSource']='Manual (session)'
        self.populate();self.refresh()

    def refresh(self,*_):
        a,b=self.by_id[self.reference],self.by_id[self.target]
        self.rows=comparison_rows(a,b)
        for snapshot in self.snapshots:
            marker = ('[A] ' if snapshot['id'] == self.reference else '') + ('[B] ' if snapshot['id'] == self.target else '')
            self.files.set(snapshot['id'], 'file', marker + Path(snapshot['path']).name)
        values=a['report']['schema45']['values'];other=b['report']['schema45']['values']
        changed=sum(r['changed'] for r in self.rows)
        groups=sorted({values[i].get('meaning',{}).get('family','') for i,r in enumerate(self.rows) if r['changed']})
        self.summary.configure(text=f"A: {Path(a['path']).name} → B: {Path(b['path']).name} | {changed} / {len(self.rows)} fields changed | Families: {', '.join(groups) or 'None'}")
        warnings=list(a['warnings'])+list(b['warnings'])
        if not a['serial'] or not b['serial']:warnings.insert(0,'Serial identity is unknown for at least one snapshot.')
        elif a['serial']!=b['serial']:warnings.insert(0,'Different instrument serials: cross-instrument comparison.')
        self.details.configure(text='\n'.join(dict.fromkeys(warnings)))
        self.table.delete(*self.table.get_children());query=self.search.get().casefold()
        for i,r in enumerate(self.rows):
            meaning=values[i].get('meaning',{});family=meaning.get('family','')
            if self.only.get() and not r['changed']:continue
            if self.family.get() not in ('All',family):continue
            if query not in (r['name']+' '+r['title']+' '+family).casefold():continue
            delta=r['interpretedDelta']
            parent=''
            if family in ('flatness','lp') and meaning.get('nameBase'):
                parent='group:'+family+':'+meaning['nameBase']
                if not self.table.exists(parent):self.table.insert('', 'end',iid=parent,text=meaning['nameBase'],open=bool(query))
            self.table.insert(parent,'end',iid=str(i),text=r['title'],values=(r['reference'],r['selected'],delta),tags=('changed',) if r['changed'] else ())
        self.raw.configure(text='');self.redraw()

    def show_detail(self,*_):
        ids=self.table.selection()
        if not self.technical.get() or not ids or not ids[0].isdigit():self.raw.configure(text='');return
        r=self.rows[int(ids[0])]
        self.raw.configure(text=f"{r['name']} | A: {r['referenceRaw']} | B: {r['selectedRaw']} | Stored delta: {r['delta']} | Bytes: {r['referenceHex']} → {r['selectedHex']}")

    def export_csv(self):
        path = filedialog.asksaveasfilename(parent=self, title='Export current comparison',
                                           defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not path:
            return
        from .cal_compare_export import export_comparison_csv
        indices = [i for i in range(len(self.rows)) if self.table.exists(str(i))]
        try:
            count = export_comparison_csv(path, self.by_id[self.reference], self.by_id[self.target],
                [self.rows[i] for i in indices], [self.rows[i]['interpretedDelta'] for i in indices],
                filters=f'Only changed={self.only.get()}; Family={self.family.get()}; Search={self.search.get()}')
        except (OSError, ValueError) as exc:
            messagebox.showerror('CSV export failed', str(exc), parent=self)
            return
        messagebox.showinfo('Comparison exported', f'{count} coefficient rows saved to:\n{path}', parent=self)

    def redraw(self,*_):
        if not hasattr(self,'canvas'):return
        c=self.canvas;c.delete('all');choice=self.choice_map.get(self.metric.get())
        if not choice:return
        trend=snapshot_trend(self.snapshots,choice['name'],self.reference)
        if not trend['available']:
            self.plot_note.configure(text=trend['reason']);return
        pts=trend['points']
        self.plot_note.configure(text=f"{choice['title']}: change relative to A, in {trend['unit']}. {len(pts)} dated snapshots. Hover a point for its details.")
        if not pts:return
        w,h=max(c.winfo_width(),600),max(c.winfo_height(),230)
        left,right,top,bottom=85,w-30,25,h-55
        xs=[p['x'] for p in pts];ys=[p['y'] for p in pts]
        lo,hi=min(xs),max(xs);yl,yh=min(ys),max(ys);pad=(yh-yl)*.08 or abs(yl)*.08 or 1;yl-=pad;yh+=pad
        xc=lambda x:(left+right)/2 if hi==lo else left+(x-lo)/(hi-lo)*(right-left)
        yc=lambda y:bottom-(y-yl)/(yh-yl)*(bottom-top)
        for i in range(5):
            y=yl+(yh-yl)*i/4;c.create_line(left,yc(y),right,yc(y),fill='#ddd');c.create_text(left-5,yc(y),text=f'{y:.5g}',anchor='e')
        c.create_line(left,top,left,bottom,right,bottom,fill='#555')
        for x,anchor in [(lo,'w'),(hi,'e')] if hi!=lo else [(lo,'center')]:
            c.create_text(xc(x),bottom+16,text=datetime.fromtimestamp(x,timezone.utc).strftime('%Y-%m-%d %H:%M'),anchor=anchor)
        c.create_text((left+right)/2,h-8,text='Backup date/time (UTC; actual time intervals)')
        for i,p in enumerate(pts):
            x,y=xc(p['x']),yc(p['y']);tag=f'point{i}'
            c.create_oval(x-4,y-4,x+4,y+4,fill='#1769aa',outline='white',tags=(tag,))
            c.tag_bind(tag,'<Enter>',lambda e,p=p:self.plot_note.configure(text=f"{Path(self.by_id[p['id']]['path']).name}: {datetime.fromtimestamp(p['x'],timezone.utc).isoformat()} | {p['y']:+.8g} {trend['unit']}"))
