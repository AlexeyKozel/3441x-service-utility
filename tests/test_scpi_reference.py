"""The hidden command reference remains usable entirely offline."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utility3441x.scpi_reference import load_reference, search_commands, command_text, build_reference_tab
from utility3441x.cli import main


class ReferenceTests(unittest.TestCase):
    def test_review_covers_every_card_without_exposing_execution(self):
        data = load_reference()
        self.assertEqual(data['coverage']['reviewed_operation_forms'], 108)
        self.assertEqual(len(data['commands']), 108)
        for row in data['commands']:
            self.assertTrue(row['reviewed_package'])
            self.assertTrue(row['summary'])
            self.assertNotIn('execute', row)

    def test_selector_results_keep_measurement_and_test_distinct(self):
        rows = {r['id']: r for r in load_reference()['commands']}
        measured = rows['0x00769bf0-query']['selectors']
        tested = rows['0x00769c04-query']['selectors']
        self.assertEqual({r['selector'] for r in measured}, {str(i) for i in range(600, 624)})
        test610 = next(r for r in tested if r['selector'] == '610')
        self.assertIn('NaN', test610['response'])
        self.assertIn('0 for pass', test610['response'])
        self.assertIn('Selectors and results', command_text(rows['0x00769a74-query']))
        self.assertIn('Elapsed Time Hours', command_text(rows['0x00769a74-query']))

    def test_corrected_reboot_binding_and_binary_input(self):
        rows = {r['id']: r for r in load_reference()['commands']}
        reboot = command_text(rows['0x00769b48-set'])
        self.assertIn('doReboot', reboot)
        self.assertNotIn('doUpdateReboot', reboot)
        self.assertIn('0x4000', reboot)
        self.assertIn('#<n><len><payload>', rows['0x007685bc-set']['syntax'])

    def test_parser_grammar_separates_query_and_write_arguments(self):
        rows = {(r['registration']['fcode']['global_symbol'], r['form']): r
                for r in load_reference()['commands']}
        self.assertEqual(rows['FCOD_diagNoOp', 'Write']['syntax'], 'DIAG:NOP')
        self.assertEqual(rows['FCOD_diagLogLevel', 'Query']['syntax'], 'DIAG:LOG:LEV?')
        self.assertIn('<int16>', rows['FCOD_diagLogLevel', 'Write']['syntax'])
        self.assertIn('[(STATic|CURRent)]', rows['FCOD_diagHostNameFcode', 'Query']['syntax'])
        self.assertFalse(rows['FCOD_calDataFcode', 'Write']['grammar']['arguments'][2]['optional'])
        self.assertTrue(rows['FCOD_calDataFcode', 'Query']['grammar']['arguments'][2]['optional'])
        self.assertIn('Definite-length binary block', rows['FCOD_calDataAllFcode', 'Query']['grammar']['response'])

    def test_official_and_compatibility_commands_are_excluded(self):
        data = load_reference()
        paths = {alias.rstrip('?') for row in data['commands'] for alias in row.get('aliases', [])}
        for documented in ('*IDN', 'CAL:STOR', 'INP:IMP:AUTO', 'SENS:DET:BAND',
                           'SENS:ZERO:AUTO', 'TRIG:SEQ:LEV'):
            self.assertNotIn(documented, paths)
        self.assertTrue(search_commands(data, 'DIAG:COMM'))
        self.assertTrue(search_commands(data, 'DIAG:LOG'))
        self.assertEqual(data['coverage']['undocumented_operation_forms'], len(data['commands']))

    def test_search_hides_catalog_only_fields_until_technical_search(self):
        row = load_reference()['commands'][0]
        data = {'commands': [{**row, 'private_catalog_marker': 'catalog-only-7f21'}]}
        self.assertEqual(search_commands(data, 'catalog-only-7f21'), [])
        self.assertEqual(search_commands(data, 'catalog-only-7f21', technical=True)[0]['id'], row['id'])
        self.assertEqual(search_commands(data, row['syntax'])[0]['id'], row['id'])

    def test_aliases_share_a_card_but_operation_forms_stay_separate(self):
        data = load_reference()
        for form in ('Write', 'Query'):
            rows = [row for row in data['commands'] if row['form'] == form
                    and row['registration']['fcode']['global_symbol'] == 'FCOD_calDataFcode']
            self.assertEqual(len(rows), 1)
            suffix = '?' if form == 'Query' else ''
            self.assertIn('CAL:DATA' + suffix, rows[0]['aliases'])
            self.assertIn('CALIBRATION:DATA' + suffix, rows[0]['aliases'])
        # Documented queries must not leak back in with the undocumented setters.
        for name in ('ROUT:TERM', 'SYST:COMM:LAN:LIP'):
            rows = [row for row in data['commands'] if name in row['aliases']]
            self.assertEqual([row['form'] for row in rows], ['Write'])

    def test_catalog_scope_and_evidence(self):
        data = load_reference()
        self.assertTrue(data['commands'])
        self.assertEqual(len({r['id'] for r in data['commands']}), len(data['commands']))
        for row in data['commands']:
            self.assertTrue(row['documentation'])
            self.assertTrue(row['evidence'])
            self.assertTrue(row['handler'])
            self.assertTrue(row['applicability'])
            self.assertNotIn(row['syntax'].upper(), ('CAL:STORE', '*IDN?'))
            self.assertIn(row['level'], ('REGISTERED', 'PARTIAL', 'HANDLER_TRACED', 'CONDITIONS_TRACED'))
            self.assertNotIn('Evidence\n', command_text(row))
            self.assertIn('Evidence\n', command_text(row, technical=True))

    def test_cli_does_not_open_instrument(self):
        output = io.StringIO()
        with patch('utility3441x.cli.VisaInstrument', side_effect=AssertionError('Reference must be offline')):
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['scpi-reference', '--search', 'CAL:DATA']), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report['commands'])
        self.assertEqual(search_commands(report, 'does-not-exist'), [])

    def test_gui_search_and_empty_selection(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        root.withdraw()
        view = build_reference_tab(root)
        view.pack()
        root.update()
        view.search.set('CAL:DATA')
        root.update()
        self.assertTrue(view.table.get_children())
        self.assertIn('Firmware handler', view.detail.get('1.0', 'end'))
        self.assertEqual(view.table['columns'], ('command', 'form', 'summary'))
        view.copy_syntax.invoke()
        self.assertEqual(root.clipboard_get(), view.rows[view.table.selection()[0]]['syntax'])

        # A selector-only query selects its matching result in the chooser, while the
        # detail pane shows just that selector instead of dumping every result.
        view.search.set('Elapsed Time Hours')
        root.update()
        self.assertNotEqual(view.selector.get(), 'Common information')
        self.assertIn('Selected selector', view.detail.get('1.0', 'end'))
        self.assertIn('Elapsed Time Hours', view.detail.get('1.0', 'end'))
        view.search.set('DIAG:PEEK 24')
        root.update()
        self.assertTrue(view.selector.get().startswith('24'))
        view.copy_card.invoke()
        self.assertIn('Selected selector', root.clipboard_get())

        view.search.set('does-not-exist')
        root.update()
        self.assertEqual(view.table.get_children(), ())
        self.assertIn('No matching commands', view.detail.get('1.0', 'end'))


if __name__ == '__main__':
    unittest.main()
