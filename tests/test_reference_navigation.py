"""Offline cross-reference navigation and readable CLI output."""
import contextlib
import io
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utility3441x.cli import main
from utility3441x.scpi_links import COMMAND_TOPICS, open_topic, topics_for_command
from utility3441x.scpi_reference import load_reference


class NavigationTests(unittest.TestCase):
    def test_links_have_existing_cards_and_pages(self):
        from utility3441x.cal_guide import PAGES
        rows = {r['id']: r for r in load_reference()['commands']}
        for identifier, topics in COMMAND_TOPICS.items():
            self.assertIn(identifier, rows)
            self.assertTrue(rows[identifier]['syntax'].startswith('CAL:DATA'))
            self.assertEqual(topics_for_command(rows[identifier]), list(topics))
            self.assertTrue(all(topic in PAGES for topic in topics))

    def test_text_cli_remains_offline(self):
        out = io.StringIO()
        with patch('utility3441x.cli.VisaInstrument', side_effect=AssertionError('Offline only')):
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['scpi-reference', '--format', 'text', '--search', 'Elapsed Time Hours']), 0)
        self.assertIn('Elapsed Time Hours', out.getvalue())
        self.assertIn('DIAG:PEEK', out.getvalue())
        self.assertNotIn('Registration grammar', out.getvalue())

    def test_general_page_needs_no_cal_file(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        root.withdraw()
        window = open_topic(root, 'storage')
        root.update()
        guide = window.winfo_children()[0]
        self.assertIn('current registered calibration values', guide.text.get('1.0', 'end'))
        self.assertEqual(guide.table.get_children(), ())
        with patch('utility3441x.scpi_links.open_commands') as commands:
            guide.commands_button.invoke()
            commands.assert_called_once_with(guide, 'storage')

    def test_selected_selector_retains_limits_and_historical_grammar_is_separate(self):
        from utility3441x.scpi_reference import _selector_text, _common_card_text
        row = next(r for r in load_reference()['commands'] if r['id'] == '0x00769c04-query')
        selector = next(s for s in row['selectors'] if s['selector'] == '610')
        rendered = _selector_text(selector)
        self.assertIn('NaN', rendered)
        for key, value in selector.items():
            self.assertIn(key.replace('_', ' ').capitalize() + ':', rendered)
        self.assertNotIn('Registration grammar', _common_card_text(row, technical=True))


if __name__ == '__main__':
    unittest.main()
