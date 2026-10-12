"""Flat CSV export of the visible A/B coefficient comparison."""
import csv
from pathlib import Path


def _text(value):
    value = str(value) if value is not None else ''
    # Prevent metadata or names being interpreted as spreadsheet formulas.
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def export_comparison_csv(path, reference, selected, rows, changes, *, filters):
    """Export filtered leaf rows, including rows inside collapsed filter groups."""
    def metadata(s):
        return [s['path'], s.get('serial') or '',
                s['date'].isoformat() if s.get('date') else '', s.get('dateSource',''),
                s['report'].get('sha256','')]
    context = metadata(reference) + metadata(selected)
    columns = ['parameter','label','changed','reference_display','selected_display',
               'interpreted_change_B_minus_A','reference_stored','selected_stored',
               'stored_delta_B_minus_A','reference_hex','selected_hex',
               'reference_file','reference_serial','reference_saved_utc','reference_date_source','reference_sha256',
               'selected_file','selected_serial','selected_saved_utc','selected_date_source','selected_sha256',
               'view_filters']
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row, change in zip(rows, changes, strict=True):
            # Raw representations/hex retain detail hidden by display rounding.
            writer.writerow([_text(v) for v in [row['name'],row['title'],str(row['changed']).lower(),
                row['reference'],row['selected'],change,row['referenceRaw'],row['selectedRaw'],row['delta'],
                row['referenceHex'],row['selectedHex'],*context,filters]])
    return len(rows)
