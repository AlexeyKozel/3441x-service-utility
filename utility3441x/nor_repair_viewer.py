"""Offline NOR repair form; computations use the application's worker queue."""
import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

from .nor_repair import plan_repair, save_plan, summary


class NorRepairViewer(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.title('NOR repair — offline')
        self.geometry('850x490')
        self.columnconfigure(1, weight=1)
        self.fields = {}
        labels = [('target','Target NOR dump'), ('cal','CAL source (payload, journal or NOR)'),
                  ('app','APP source (XS or NOR)'), ('recovery','Recovery source (NOR, complete XS or CPU image)')]
        for row,(key,label) in enumerate(labels):
            ttk.Label(self,text=label).grid(row=row,column=0,sticky='w',padx=8,pady=6)
            var=tk.StringVar(); self.fields[key]=var
            ttk.Entry(self,textvariable=var).grid(row=row,column=1,sticky='ew',padx=4)
            def choose(v=var, title=label):
                p=filedialog.askopenfilename(parent=self,title=title)
                if p: v.set(p)
            ttk.Button(self,text='Browse…',command=choose).grid(row=row,column=2,padx=8)
        self.order=tk.StringVar(value='auto'); self.donor_order=tk.StringVar(value='auto')
        self.model=tk.StringVar(value='From Recovery content')
        for row,label,var,choices in [
            (4,'Target byte order',self.order,('auto','cpu','programmer')),
            (5,'Donor NOR byte order',self.donor_order,('auto','cpu','programmer')),
            (6,'Model if Recovery content is unknown',self.model,('From Recovery content','34410A','34411A','L4411A'))]:
            ttk.Label(self,text=label).grid(row=row,column=0,sticky='w',padx=8,pady=4)
            ttk.Combobox(self,textvariable=var,values=choices,state='readonly').grid(row=row,column=1,sticky='w')
        self.reset=tk.BooleanVar(value=False)
        self.overwrite_cal=tk.BooleanVar(value=False)
        ttk.Checkbutton(self,text='Also restore reset vector from Recovery source',variable=self.reset).grid(row=7,column=0,columnspan=3,sticky='w',padx=8,pady=6)
        ttk.Checkbutton(self,text='Overwrite CAL journal with selected calibrations (output file only)',variable=self.overwrite_cal).grid(row=8,column=0,columnspan=3,sticky='w',padx=8,pady=6)
        ttk.Label(self,text='Leave unused source fields empty. Original files are preserved.\n'
                  'Identity is checked against decompressed Recovery content, not the SA96 personality code.\n'
                  'Overwrite removes all previous CAL records from the output and leaves only the selected CAL.\n'
                  'Without Overwrite, existing history is preserved and a free slot is required.',
                  wraplength=800).grid(row=9,column=0,columnspan=3,sticky='w',padx=8,pady=8)
        def run(save=False):
            args={k:(Path(v.get()) if v.get().strip() else None) for k,v in self.fields.items()}
            if not args['target']:
                return
            args.update(order=self.order.get(),donor_order=self.donor_order.get(),
                        model=None if self.model.get()=='From Recovery content' else self.model.get(),
                        restore_reset=self.reset.get(),overwrite_cal_journal=self.overwrite_cal.get())
            output=None
            if save:
                filename=filedialog.asksaveasfilename(parent=self,title='Save repaired NOR as a NEW file',defaultextension='.bin')
                if not filename: return
                output=Path(filename)
            def operation():
                plan=plan_repair(**args)
                description=summary(plan)
                if output is None: return description
                if not app._confirm_yes_no_from_worker('Save repaired NOR',description+'\n\nSave new file: '+str(output)+'?'):
                    return 'NOR repair cancelled; no file saved.'
                save_plan(plan,output)
                return description+'\n\nSaved: '+str(output)+'\nReport: '+str(output)+'.json'
            app._run_worker('Planning offline NOR repair',operation)
        bar=ttk.Frame(self);bar.grid(row=10,column=0,columnspan=3,sticky='w',padx=8,pady=8)
        ttk.Button(bar,text='Preview in main log',command=lambda:run(False)).pack(side='left',padx=4)
        ttk.Button(bar,text='Save repaired dump…',command=lambda:run(True)).pack(side='left',padx=4)
