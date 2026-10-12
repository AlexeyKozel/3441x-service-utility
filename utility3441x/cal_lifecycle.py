"""Presentation of bounded coefficient calculation and application cards."""
from __future__ import annotations


def lifecycle_text(card: dict, *, technical: bool = False) -> str:
    lifecycle = card.get('lifecycle')
    if not lifecycle:
        return 'Calculation and use: no detailed card is available for this family yet.'
    lines = ['Calculation and use', lifecycle['scope']]
    for key, title in (('calculation', 'How it is calculated'),
                       ('application', 'How it is used'),
                       ('selection', 'When it applies'),
                       ('activation', 'When changes take effect'),
                       ('related', 'Related coefficients')):
        section = lifecycle[key]
        lines.extend(['', title, section['text']])
        if technical:
            lines.append('Evidence: ' + section['status'])
            lines.extend(section.get('references', []))
    return '\n'.join(lines)
