"""Numerical and fail-closed checks for the read-only CAL display projection."""
from __future__ import annotations

import copy
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utility3441x.cal_display import build_display
from utility3441x.offline import load_schema45_registry, parse_cal_payload


ROWS = load_schema45_registry()["registry"]["rows"]
BY_NAME = {row["name"]: row for row in ROWS}


def report(changes=None, *, version=45, corrupt=False):
    body = bytearray(4924)
    for name, value in (changes or {}).items():
        row = BY_NAME[name]
        struct.pack_into(">d" if row["type"] == "double" else ">i",
                         body, row["offset"], value)
    check = (~sum(body)) & 0xFFFFFFFF
    payload = struct.pack(">HII", version, len(body), check ^ int(corrupt)) + body
    return parse_cal_payload(payload, explain=True)


def by_name(cards):
    return {card["name"]: card for card in cards}


class CalDisplayTests(unittest.TestCase):
    def test_adc_timing_positions_use_matching_profile_and_boundaries(self):
        values = {"Adc_N_Decisions[DCV]": 106, "Adc_Nf_Slope[DCV]": 30,
                  "Adc_FineSamplOffset[DCV]": 4,
                  "Adc_N_Decisions[ACV]": 72, "Adc_Nf_Slope[ACV]": 16,
                  "Adc_FineSamplOffset[ACV]": 0}
        source = report(values)
        before = copy.deepcopy(source)
        cards = by_name(build_display(source))
        for profile, positions in [("DCV", (90, 14, 100)), ("ACV", (63, 7, 59))]:
            lines = cards[f"Adc_Nf_Slope[{profile}]"]["derived"]
            for line, position in zip(lines[1:4], positions):
                self.assertIn(f"= {position};", line)
            self.assertIn("stored", cards[f"Adc_Nf_Slope[{profile}]"]["value"])
        self.assertIn("= 2; nominal position 0.018823529 us", cards["Adc_FineSamplOffset[DCV]"]["derived"][1])
        self.assertIn("= 70;", cards["Adc_FineSamplOffset[ACV]"]["derived"][1])
        self.assertEqual(source, before)
        # No attractive but incorrect modulo result for negative/fractional or
        # unrepresentable inputs; checksum failure also suppresses projection.
        for changes in ({"Adc_FineSamplOffset[DCV]": -107},
                        {"Adc_N_Decisions[DCV]": 0},
                        {"Adc_N_Decisions[DCV]": 129},
                        {"Adc_FineSamplOffset[DCV]": 4.5}):
            cards = by_name(build_display(report(values | changes)))
            self.assertEqual(cards["Adc_FineSamplOffset[DCV]"]["derived"], [])
        cards = by_name(build_display(report(values, corrupt=True)))
        self.assertEqual(cards["Adc_Nf_Slope[DCV]"]["derived"], [])

    def test_adc_cycle_nominal_time_and_unusable_counts(self):
        names = [f"Adc_N_Decisions[{profile}]" for profile in ("DCV", "ACV", "ACI")]
        source = report(dict(zip(names, (106, 72, 108))))
        before = copy.deepcopy(source)
        cards = by_name(build_display(source))
        for name, duration in zip(names, ("0.99764706", "0.67764706", "1.0164706")):
            self.assertEqual(cards[name]["value"], duration + " us nominal cycle")
            self.assertIn("106.25 MHz", cards[name]["qualification"])
        self.assertEqual(source, before)
        for value in (0, -1, 129, 106.5, float("nan")):
            card = by_name(build_display(report({names[0]: value})))[names[0]]
            self.assertIn("stored", card["value"])
            self.assertEqual(card["derived"], [])
        card = by_name(build_display(report({names[0]: 106}, corrupt=True)))[names[0]]
        self.assertEqual(card["derived"], [])
        self.assertIn("stored", card["value"])

    def test_mc_mz_hypothetical_time_keeps_raw_and_unresolved_status(self):
        source = report({'McDelay': 60, 'MzDelay': 10})
        before = copy.deepcopy(source)
        named = by_name(build_display(source))
        self.assertEqual(source, before)
        for name, duration in [('McDelay', '1.197176 ms'), ('MzDelay', '0.199529 ms')]:
            card = named[name]
            self.assertIn('stored', card['value'])
            self.assertIn('unresolved', card['qualification'])
            self.assertIn('hypothetical', card['qualification'])
            self.assertIn(duration, card['derived'][0])
            self.assertIn('19.952941176 us', card['derived'][0])
            self.assertIn('not been confirmed', card['derived'][1])
        for source in (report({'McDelay': 60, 'MzDelay': 10}, corrupt=True),
                       report({'McDelay': -1, 'MzDelay': -1})):
            named = by_name(build_display(source))
            for name in ('McDelay', 'MzDelay'):
                self.assertEqual(named[name]['derived'], [])

    def test_exact_pair_range_terminal_and_bank_with_rounding_qualification(self):
        source = report({
            "DcvGain10": 2e-6, "DcvOff10": -0.75,
            "DcvOff10Rear": 0.25, "DciGain1_0m": 3e-9,
            "DciOff1_0m": -2,
            "ResGain1K": 0.5, "ResOff1K[FRONT]": 2,
            "ResGain1KOC": 2.0, "ResOff1KOC[FRONT]": 3,
            "Res4Gain1K": 0.25, "Res4Off1K[FRONT]": 4,
        })
        before = copy.deepcopy(source)
        cards = build_display(source)
        self.assertEqual(source, before)
        self.assertEqual(len(cards), 1072)
        self.assertEqual([x["name"] for x in cards], [x["name"] for x in source["schema45"]["values"]])
        named = by_name(cards)
        self.assertIn("1.5 uV", named["DcvOff10"]["value"])
        self.assertIn("-500 nV", named["DcvOff10Rear"]["value"])
        self.assertIn("6 nA", named["DciOff1_0m"]["value"])
        self.assertIn("-1 ohm", named["ResOff1K[FRONT]"]["value"])
        self.assertIn("-6 ohm", named["ResOff1KOC[FRONT]"]["value"])
        self.assertIn("-1 ohm", named["Res4Off1K[FRONT]"]["value"])
        self.assertIn("rounding", named["DcvOff10"]["qualification"])
        self.assertIn("of firmware default", named["DcvGain10"]["value"])
        self.assertIn("Voltage [V] = internal result × 2e-06",
                      named["DcvGain10"]["derived"])
        self.assertIn("Current [A] = internal result × 3e-09",
                      named["DciGain1_0m"]["derived"])

    def test_dci_reference_ratio_preserves_scale_and_names_reference(self):
        # Independent binary64 operands extracted from the firmware constructor.
        words = {'DciGain100u': '3db1fd1d13493f26',
                 'DciGain1_0m': '3de67c64581b8ef1',
                 'DciGain10m': '3e1c6371e26f97aa',
                 'DciGain100m': '3e51be272d85beca',
                 'DciGain1_0': '3e61634f5ab1267e',
                 'DciGain3_0': '3e95bc23315d701e'}
        changes = {n: struct.unpack('>d', bytes.fromhex(h))[0] * 1.045
                   for n, h in words.items()}
        source = report(changes)
        before = copy.deepcopy(source)
        named = by_name(build_display(source))
        self.assertEqual(source, before)
        for name in words:
            self.assertEqual(named[name]['value'], '×1.045 of firmware default')
            self.assertIn('APP11 2.43', named[name]['qualification'])
            self.assertIn('same offset', named[name]['description'])
            self.assertTrue(any('CAL gain:' in x for x in named[name]['derived']))
        bad = by_name(build_display(report(changes, corrupt=True)))
        self.assertIn('stored', bad['DciGain100m']['value'])
        extreme = by_name(build_display(report({'DciGain100m': 1e308})))
        self.assertNotIn('of firmware default', extreme['DciGain100m']['value'])

    def test_dcv_reference_all_ranges_and_quadratic_boundary(self):
        words = {'DcvGain0_1': '3e2bd218911b70ca',
                 'DcvGain1_0': '3e61634f5ab1267e',
                 'DcvGain10': '3e95bc23315d701e',
                 'DcvGain100': '3ecb2b2bfdb4cc25',
                 'DcvGain1000': '3f00fafb7e90ff97'}
        changes = {n: struct.unpack('>d', bytes.fromhex(h))[0] * 0.995
                   for n, h in words.items()}
        source = report(changes)
        before = copy.deepcopy(source)
        named = by_name(build_display(source))
        self.assertEqual(source, before)
        for name in words:
            self.assertEqual(named[name]['value'], '×0.995 of firmware default')
            self.assertIn('linear-stage', named[name]['description'])
            self.assertTrue(any('CAL gain:' in x and 'V per internal unit' in x
                                for x in named[name]['derived']))
        self.assertIn('before the 10 V quadratic', named['DcvGain10']['qualification'])
        self.assertNotIn('quadratic', named['DcvGain100']['qualification'])
        bad = by_name(build_display(report(changes, corrupt=True)))
        self.assertIn('stored', bad['DcvGain10']['value'])
        extreme = by_name(build_display(report({'DcvGain0_1': 1e308})))
        self.assertNotIn('of firmware default', extreme['DcvGain0_1']['value'])

    def test_resistance_reference_banks_and_high_range_boundary(self):
        words = {'100': '3ecb2b2bfdb4cc25', '1K': '3f00fafb7e90ff97',
                 '10K': '3f3539ba5e353f7e', '100K': '3f6a8828f5c28f5d',
                 '1M': '3fb095199999999a', '10M': '3fe4ba6000000000',
                 '100M': '3fe4ba6000000000', '1G': '3fe4ba6000000000',
                 '100OC': '3ece2ff7fd738d7e', '1KOC': '3f02ddfafe68386f',
                 '10KOC': '3f379579be02468b'}
        changes = {family + suffix: struct.unpack('>d', bytes.fromhex(h))[0] * factor
                   for family, factor in [('ResGain', 1.025), ('Res4Gain', 0.975)]
                   for suffix, h in words.items()}
        source = report(changes)
        before = copy.deepcopy(source)
        named = by_name(build_display(source))
        self.assertEqual(source, before)
        for family, factor in [('ResGain', '1.025'), ('Res4Gain', '0.975')]:
            for suffix in words:
                card = named[family + suffix]
                self.assertEqual(card['value'], f'×{factor} of firmware default')
                self.assertIn('before absolute value', card['qualification'])
                self.assertEqual('nonlinear divider' in card['qualification'], suffix in ('100M', '1G'))
                self.assertTrue(any('CAL gain:' in x and 'ohm per internal unit' in x
                                    for x in card['derived']))
        bad = by_name(build_display(report(changes, corrupt=True)))
        self.assertIn('stored', bad['Res4Gain1KOC']['value'])
        huge = by_name(build_display(report({'ResGain100': 1e308})))
        self.assertNotIn('of firmware default', huge['ResGain100']['value'])

    def test_ac_reference_and_zero_reference_exception(self):
        refs = {'AcvGain1000V': 186.16, 'AcvGain100V': 18.616,
                'AcvGain100mV': .018616, 'AcvGain10V': 1.8616, 'AcvGain1V': .18616,
                'AciGain1A': .42451, 'AciGain100mA': .0212255,
                'AciGain10mA': .0021225500000000004, 'AciGain1mA': .000212255,
                'AciGain100uA': .000021225500000000002}
        source = report({**{n: g*1.045 for n,g in refs.items()}, 'AciGain3A': .4})
        before = copy.deepcopy(source)
        cards = by_name(build_display(source))
        self.assertEqual(source, before)
        for name in refs:
            self.assertEqual(cards[name]['value'], '×1.045 of APP 2.43 reference')
            self.assertTrue(any('CAL gain:' in x for x in cards[name]['derived']))
            self.assertIn('not an accuracy', cards[name]['qualification'])
        self.assertEqual(cards['AciGain3A']['value'], '400 mA per internal RMS unit')
        self.assertIn('reference is zero', cards['AciGain3A']['qualification'])
        bad = by_name(build_display(report({'AcvGain10V': 1.8616}, corrupt=True)))
        self.assertIn('stored', bad['AcvGain10V']['value'])

    def test_heater_drive_uses_reciprocal_and_positive_domain(self):
        for gain, factor in ((1.33,'1'), (2.66,'0.5'), (.665,'2')):
            card = by_name(build_display(report({'HeaterGain': gain})))['HeaterGain']
            self.assertEqual(card['value'], f'×{factor} of default heater drive')
            self.assertIn('before rounding', card['qualification'])
            self.assertTrue(any('>= 300 V' in x for x in card['derived']))
        for gain in (0,-1,float('nan'),5e-324):
            card = by_name(build_display(report({'HeaterGain': gain})))['HeaterGain']
            self.assertIn('stored', card['value'])

    def test_frequency_pwm_and_internal_boundaries(self):
        named = by_name(build_display(report({"FreqGain": 1.000001,
                                              "PrechargePwm": 143,
                                              "AcvSlowNoiseGainSquared": 0.25,
                                              "Adc_FineMergeGain[DCV]": 0.001})))
        self.assertIn("ppm", named["FreqGain"]["derived"][0])
        self.assertTrue(any("Period multiplier" in x for x in named["FreqGain"]["derived"]))
        self.assertEqual(named["PrechargePwm"]["value"], "56.25% low duty")
        self.assertIn("E127/A1", named["PrechargePwm"]["qualification"])
        self.assertIn("×1.25 noise term", named["AcvSlowNoiseGainSquared"]["value"])
        self.assertTrue(named["Adc_FineMergeGain[DCV]"]["derived"])
        self.assertIn("physical equivalent not established", by_name(build_display(report()))["HeaterGain"]["qualification"])

    def test_capacitance_units_sign_and_packet_delay(self):
        source = report({'CapOffsetFront': 1.8003520230925273e-10,
                         'CapOffsetRear': -2.0489098119596379e-10,
                         'CurrentSrcDelay': 75})
        before = copy.deepcopy(source)
        named = by_name(build_display(source))
        self.assertEqual(source, before)
        self.assertEqual(named['CapOffsetFront']['value'], '180.0352 pF')
        self.assertEqual(named['CapOffsetRear']['value'], '-204.89098 pF')
        self.assertEqual(named['CapOffsetFront']['derived'], ['Reading contribution: -180.0352 pF'])
        self.assertEqual(named['CurrentSrcDelay']['value'], '75 DC packets (~1.5 ms nominal)')
        self.assertIn('before NPLC accumulation', named['CurrentSrcDelay']['description'])
        self.assertIn('19.952941176 us', named['CurrentSrcDelay']['derived'][0])
        self.assertIn('extend', named['CurrentSrcDelay']['qualification'])
        bad = by_name(build_display(report({'CapOffsetFront': 1e-10}, corrupt=True)))
        self.assertIn('stored', bad['CapOffsetFront']['value'])
        self.assertEqual(bad['CapOffsetFront']['derived'], [])
        negative = by_name(build_display(report({'CurrentSrcDelay': -1})))
        self.assertIn('stored', negative['CurrentSrcDelay']['value'])
        one_plc = by_name(build_display(report({'CurrentSrcDelay': 1002})))
        self.assertEqual(one_plc['CurrentSrcDelay']['value'], '1002 DC packets (~20 ms nominal)')
        # Distinguishes the firmware's explicit seconds/count constant from
        # an inferred 1 / 50100 scale at the displayed rounding boundary.
        scaled = by_name(build_display(report({'CurrentSrcDelay': 125})))
        self.assertEqual(scaled['CurrentSrcDelay']['value'], '125 DC packets (~2.49 ms nominal)')
        zero = by_name(build_display(report({'CurrentSrcDelay': 0})))
        self.assertIn('~0 ms nominal', zero['CurrentSrcDelay']['value'])
        self.assertIn('extend', zero['CurrentSrcDelay']['qualification'])

    def test_bad_integrity_unknown_schema_and_nonfinite_never_derive(self):
        for source in (report({"DcvGain10": 2e-6}, corrupt=True),
                       report({"DcvGain10": 2e-6}, version=44)):
            cards = build_display(source)
            self.assertEqual(len(cards), 1072)
            self.assertEqual(by_name(cards)["DcvGain10"]["derived"], [])
            self.assertIn("stored", by_name(cards)["DcvGain10"]["value"])
        source = report({"DcvGain10": float("nan"), "DcvOff10": 2})
        named = by_name(build_display(source))
        self.assertIn("Non-finite", named["DcvGain10"]["qualification"])
        self.assertIn("stored", named["DcvOff10"]["value"])

    def test_every_family_has_a_card_without_invented_unit(self):
        source = report()
        cards = build_display(source)
        self.assertEqual(len({v["meaning"]["family"] for v in source["schema45"]["values"]}), 38)
        self.assertTrue(all(c["title"] and c["value"] and c["description"]
                            and c["qualification"] for c in cards))
        named = by_name(cards)
        self.assertIn("unresolved", named["McDelay"]["qualification"])
        self.assertIn("stored", named["HeaterGain"]["value"])

    def test_noise_equivalent_does_not_invent_rms_for_negative_power(self):
        cards = by_name(build_display(report({'AcvGain10V': 2.0, 'AcvSqNoise10V': .25})))
        self.assertEqual(cards['AcvSqNoise10V']['value'], '1 V RMS equivalent')
        self.assertIn('MED/FAST', cards['AcvSqNoise10V']['qualification'])
        cards = by_name(build_display(report({'AcvGain10V': 2.0, 'AcvSqNoise10V': -.25})))
        self.assertEqual(cards['AcvSqNoise10V']['value'], '-1 V² equivalent')
        self.assertFalse(any('RMS term:' in x for x in cards['AcvSqNoise10V']['derived']))

    def test_pwm_rounding_and_fir_vector_identity(self):
        cards = by_name(build_display(report({'PrechargePwm': 143.5})))
        self.assertEqual(cards['PrechargePwm']['value'], '56.640625% low duty')
        self.assertNotEqual(cards['Acv100mVFlatnessCoefs[0]']['title'],
                            cards['Aci100uAFlatnessCoefs[0]']['title'])


if __name__ == "__main__":
    unittest.main()
