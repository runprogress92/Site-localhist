"""Tests des modules scientifiques.

Chaque test vérifie soit un **ancrage** (une valeur que le modèle doit
reproduire par construction : une heure au seuil vaut 100 points), soit un
**invariant** (une propriété qui doit tenir quelles que soient les données :
la puissance normalisée d'un effort constant égale sa moyenne).
"""
import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.science import hrv, load, physiology, pmc, power, readiness, risk
from backend.science import running as run_mod
from backend.science import zones


class TestZones(unittest.TestCase):
    def test_coggan_boundaries(self):
        z = zones.power_zones(250)
        self.assertEqual(len(z), 7)
        self.assertAlmostEqual(z[3]["low"], 250 * 0.91, places=2)   # bas de Z4
        self.assertAlmostEqual(z[3]["high"], 250 * 1.06, places=2)
        self.assertIsNone(z[0]["low"])
        self.assertIsNone(z[-1]["high"])

    def test_zones_are_contiguous(self):
        """La borne haute d'une zone est la borne basse de la suivante."""
        for z in (zones.power_zones(280), zones.hr_zones("friel_lthr", lthr=170)):
            for a, b in zip(z, z[1:]):
                self.assertEqual(a["high"], b["low"])

    def test_karvonen_uses_reserve(self):
        z = zones.hr_zones("karvonen", hr_max=200, hr_rest=50)
        # 60 % de réserve = 50 + 0,60 × 150 = 140
        self.assertAlmostEqual(z[1]["low"], 140, places=1)

    def test_time_in_zones_conserves_total(self):
        series = [120, 140, 150, 165, 180, 195] * 100
        z = zones.hr_zones("hrmax", hr_max=200)
        seconds = zones.time_in_zones(series, z)
        self.assertAlmostEqual(sum(seconds), len(series), places=6)

    def test_polarization_index(self):
        # 80/5/15 est une distribution nettement polarisée
        self.assertGreater(zones.polarization_index(80, 5, 15), 2.0)
        # 60/30/10 ne l'est pas
        self.assertLess(zones.polarization_index(60, 30, 10), 2.0)


class TestLoad(unittest.TestCase):
    def test_tss_anchor(self):
        """Une heure exactement à la FTP vaut 100 points, par définition."""
        self.assertAlmostEqual(load.tss(3600, 250, 250), 100.0, places=1)

    def test_tss_scales_quadratically_with_intensity(self):
        base = load.tss(3600, 200, 250)
        double = load.tss(3600, 400, 250)
        self.assertAlmostEqual(double / base, 4.0, places=2)

    def test_hrtss_anchor(self):
        """Une heure à la FC du seuil vaut aussi 100 points."""
        value = load.hrtss(3600, None, 168, 45, 190, 168, "M")
        self.assertAlmostEqual(value, 100.0, delta=0.5)

    def test_hrtss_below_threshold_is_lower(self):
        easy = load.hrtss(3600, None, 130, 45, 190, 168, "M")
        self.assertLess(easy, 60)

    def test_rtss_anchor(self):
        self.assertAlmostEqual(load.rtss(3600, 4.0, 4.0), 100.0, places=1)

    def test_trimp_series_more_exact_than_mean(self):
        """L'exponentielle du TRIMP rend la version intégrée supérieure à la
        version moyennée dès que l'intensité varie (inégalité de Jensen)."""
        series = [120] * 1800 + [180] * 1800
        integrated = load.trimp_banister_series(series, 45, 195, "M")
        averaged = load.trimp_banister(3600, 150, 45, 195, "M")
        self.assertGreater(integrated, averaged)

    def test_best_load_prefers_pace_for_running(self):
        value, source = load.best_load(tss_v=90, rtss_v=85, hrtss_v=80, sport="running")
        self.assertEqual(source, "rtss")
        value, source = load.best_load(tss_v=90, rtss_v=85, hrtss_v=80, sport="cycling")
        self.assertEqual(source, "tss")

    def test_missing_data_returns_none(self):
        self.assertIsNone(load.tss(3600, None, 250))
        self.assertIsNone(load.hrtss(3600, None, 150, None, None, None))


class TestPower(unittest.TestCase):
    def test_np_of_constant_equals_mean(self):
        self.assertEqual(power.normalized_power([250] * 1200), 250.0)

    def test_np_of_intervals_exceeds_mean(self):
        series = ([400] * 60 + [100] * 60) * 20
        mean = sum(series) / len(series)
        self.assertGreater(power.normalized_power(series), mean * 1.15)

    def test_mmp_is_monotonically_decreasing(self):
        import random
        random.seed(4)
        series = [200 + random.gauss(0, 60) for _ in range(3600)]
        curve = power.mean_maximal(series, [5, 60, 300, 1200, 3600])
        values = [curve[d][0] for d in sorted(curve)]
        for a, b in zip(values, values[1:]):
            self.assertGreaterEqual(a, b - 1e-6)

    def test_critical_power_recovers_known_parameters(self):
        """Sur des points générés par le modèle, l'ajustement doit retrouver
        les paramètres d'origine."""
        cp, w_prime = 300.0, 20000.0
        efforts = [(t, cp + w_prime / t) for t in (180, 300, 600, 900, 1200)]
        model = power.critical_power(efforts)
        self.assertAlmostEqual(model["cp_w"], cp, delta=1.0)
        self.assertAlmostEqual(model["w_prime_j"], w_prime, delta=200)
        self.assertGreater(model["r2"], 0.999)

    def test_morton_model_is_bounded_by_pmax(self):
        """Le modèle à 3 paramètres ne doit jamais dépasser Pmax."""
        for t in (1, 2, 5, 10, 30):
            self.assertLessEqual(power.power_duration(t, 300, 20000, 1200), 1200.0)
        # et il tend vers CP aux durées longues
        self.assertAlmostEqual(power.power_duration(36000, 300, 20000, 1200), 300, delta=1)

    def test_w_bal_depletes_and_recovers(self):
        series = [400] * 100 + [150] * 900
        balance = power.w_bal(series, 300, 20000)
        # 100 s à 100 W au-dessus de CP consomment 10 kJ
        self.assertAlmostEqual(min(balance), 10000, delta=100)
        self.assertGreater(balance[-1], min(balance))     # reconstitution
        self.assertLessEqual(max(balance), 20000)          # jamais au-dessus de W'

    def test_decoupling_detects_drift(self):
        constant = power.aerobic_decoupling([250] * 3600, [150] * 3600)
        self.assertAlmostEqual(constant, 0.0, places=1)
        drifting = power.aerobic_decoupling([250] * 3600, [140] * 1800 + [154] * 1800)
        self.assertGreater(drifting, 8)

    def test_decoupling_none_when_too_short(self):
        self.assertIsNone(power.aerobic_decoupling([250] * 600, [150] * 600))


class TestRunning(unittest.TestCase):
    def test_minetti_flat_cost(self):
        self.assertAlmostEqual(run_mod.grade_cost(0.0), 3.6, places=6)
        self.assertAlmostEqual(run_mod.grade_factor(0.0), 1.0, places=6)

    def test_uphill_costs_more_downhill_less(self):
        self.assertGreater(run_mod.grade_factor(0.10), 1.5)
        self.assertLess(run_mod.grade_factor(-0.10), 1.0)

    def test_gap_slows_on_climb(self):
        """À vitesse constante en montée, l'allure ajustée est plus rapide que
        l'allure brute — la pente a coûté plus cher."""
        speed = [3.0] * 600
        altitude = [i * 0.3 for i in range(600)]     # +30 % de pente
        gap = run_mod.gap_speed_series(speed, altitude)
        self.assertGreater(sum(gap[100:]) / 500, 3.0)

    def test_vdot_matches_published_table(self):
        # Daniels : 10 km en 40:00 correspond à un VDOT d'environ 52
        self.assertAlmostEqual(run_mod.vdot(10000, 2400), 52, delta=1.0)
        # 5 km en 20:00 correspond à environ 49
        self.assertAlmostEqual(run_mod.vdot(5000, 1200), 49.8, delta=1.0)

    def test_daniels_paces_are_ordered(self):
        paces = run_mod.daniels_paces(52)
        order = ["easy", "marathon", "threshold", "interval", "repetition"]
        speeds = [paces[k]["speed_max_ms"] for k in order]
        for a, b in zip(speeds, speeds[1:]):
            self.assertLess(a, b)

    def test_riegel_marathon_prediction(self):
        # 10 km en 40:00 prédit un marathon autour de 3 h 04
        seconds = run_mod.riegel_predict(10000, 2400, 42195)
        self.assertAlmostEqual(seconds / 60, 184, delta=3)

    def test_critical_speed_recovers_parameters(self):
        cs, d_prime = 4.5, 200.0
        efforts = [(t, cs * t + d_prime) for t in (180, 300, 600, 900)]
        model = run_mod.critical_speed(efforts)
        self.assertAlmostEqual(model["cs_ms"], cs, places=3)
        self.assertAlmostEqual(model["d_prime_m"], d_prime, delta=1)

    def test_pace_conversions_roundtrip(self):
        self.assertAlmostEqual(run_mod.pace_to_speed(run_mod.speed_to_pace(4.0)),
                               4.0, places=3)


class TestPMC(unittest.TestCase):
    def setUp(self):
        self.start = date(2025, 1, 1)
        self.end = date(2025, 12, 31)

    def _series(self, daily_load):
        daily = {}
        day = self.start
        while day <= self.end:
            daily[day.isoformat()] = daily_load
            day += timedelta(days=1)
        return pmc.compute_pmc(daily, self.start, self.end)

    def test_ctl_converges_to_constant_load(self):
        """Sous charge constante, CTL et ATL convergent vers cette charge."""
        series = self._series(60)
        self.assertAlmostEqual(series[-1]["ctl"], 60, delta=0.6)
        self.assertAlmostEqual(series[-1]["atl"], 60, delta=0.1)
        self.assertAlmostEqual(series[-1]["tsb"], 0, delta=1.0)

    def test_atl_reacts_faster_than_ctl(self):
        series = self._series(80)
        early = series[10]
        self.assertGreater(early["atl"], early["ctl"])

    def test_tsb_is_lagged_difference(self):
        """TSB du jour = CTL(j−1) − ATL(j−1), convention TrainingPeaks.

        La tolérance vaut 0,02 : les valeurs sont stockées arrondies au
        centième, et l'écart de deux arrondis n'est pas l'arrondi de l'écart.
        """
        series = self._series(50)
        for i in range(1, len(series)):
            expected = series[i - 1]["ctl"] - series[i - 1]["atl"]
            self.assertAlmostEqual(series[i]["tsb"], expected, delta=0.02)

    def test_acwr_is_one_under_constant_load(self):
        series = self._series(70)
        self.assertAlmostEqual(series[-1]["acwr_rolling"], 1.0, places=2)

    def test_missing_days_count_as_rest(self):
        """Un jour sans séance ne doit pas être ignoré : c'est du repos."""
        daily = {self.start.isoformat(): 100}
        series = pmc.compute_pmc(daily, self.start, self.start + timedelta(days=41))
        self.assertLess(series[-1]["ctl"], series[0]["ctl"] + 3)
        self.assertLess(series[-1]["atl"], 1.0)

    def test_taper_reaches_target(self):
        loads = pmc.taper_plan(70, 75, days=14, target_tsb=20)
        final = pmc.project_forward(70, 75, loads)[-1]
        self.assertAlmostEqual(final["tsb"], 20, delta=0.6)

    def test_taper_holds_before_tapering(self):
        """Sur un horizon long, la charge est maintenue puis réduite."""
        loads = pmc.taper_plan(80, 80, days=60, target_tsb=15, taper_days=14)
        self.assertEqual(len(loads), 60)
        self.assertAlmostEqual(loads[0], 80, delta=0.5)      # maintien
        self.assertLess(loads[-1], 60)                        # affûtage

    def test_form_states_ordered(self):
        self.assertEqual(pmc.form_state(30)[0], "affûté")
        self.assertEqual(pmc.form_state(0)[0], "neutre")
        self.assertEqual(pmc.form_state(-40)[0], "surcharge")


class TestHRV(unittest.TestCase):
    def test_rmssd_of_constant_intervals_is_zero(self):
        self.assertEqual(hrv.rmssd([1000] * 100), 0.0)

    def test_rmssd_known_value(self):
        # alternance ±50 ms : toutes les différences valent 100 ms
        series = [1000, 1100] * 50
        self.assertAlmostEqual(hrv.rmssd(series), 100.0, places=1)

    def test_artifact_correction_removes_ectopic(self):
        series = [1000] * 10 + [400] + [1000] * 10
        corrected = hrv.artifact_correction(series)
        self.assertAlmostEqual(corrected[10], 1000, delta=1)

    def test_normal_range_brackets_mean(self):
        import random
        random.seed(9)
        values = [math.log(60 + random.gauss(0, 5)) for _ in range(60)]
        low, mean, high = hrv.normal_range(values)
        self.assertLess(low, mean)
        self.assertLess(mean, high)

    def test_status_detects_suppression(self):
        status = hrv.hrv_status(3.5, 4.0, 4.2)
        self.assertEqual(status["status"], "supprimée")
        self.assertEqual(status["level"], 3)


class TestReadiness(unittest.TestCase):
    def test_baseline_gives_middle_score(self):
        result = readiness.readiness(
            ln_rmssd=4.0, hrv_baseline=4.0, hrv_sd=0.1,
            rhr=45, rhr_baseline=45, sleep_min=480, sleep_quality=4,
            fatigue=4, soreness=4, mood=4, stress=4, tsb=0, acwr=1.0)
        self.assertAlmostEqual(result["score"], 60, delta=12)

    def test_score_improves_with_better_inputs(self):
        common = dict(hrv_baseline=4.0, hrv_sd=0.15, rhr_baseline=48)
        good = readiness.readiness(ln_rmssd=4.3, rhr=44, sleep_min=520,
                                   sleep_quality=1, fatigue=1, soreness=1,
                                   mood=1, stress=1, tsb=10, acwr=1.0, **common)
        bad = readiness.readiness(ln_rmssd=3.6, rhr=54, sleep_min=330,
                                  sleep_quality=6, fatigue=6, soreness=6,
                                  mood=6, stress=6, tsb=-30, acwr=1.7, **common)
        self.assertGreater(good["score"], bad["score"] + 35)
        self.assertEqual(good["flag"], "vert")
        self.assertEqual(bad["flag"], "rouge")

    def test_partial_data_still_scores(self):
        """Un questionnaire seul doit suffire à produire un score."""
        result = readiness.readiness(fatigue=2, soreness=2, mood=2, stress=2)
        self.assertIsNotNone(result["score"])
        self.assertLess(result["coverage"], 0.5)

    def test_no_data_returns_none(self):
        self.assertIsNone(readiness.readiness()["score"])

    def test_weights_are_renormalised(self):
        """Le score ne doit pas dépendre du nombre de composantes disponibles
        lorsque celles-ci valent toutes la même chose."""
        full = readiness.readiness(
            ln_rmssd=4.0, hrv_baseline=4.0, hrv_sd=0.1, rhr=45, rhr_baseline=45)
        partial = readiness.readiness(ln_rmssd=4.0, hrv_baseline=4.0, hrv_sd=0.1)
        self.assertAlmostEqual(full["score"], partial["score"], delta=1.0)


class TestPhysiology(unittest.TestCase):
    def test_hrmax_formulas_are_close(self):
        tanaka = physiology.estimate_hr_max(30, "M", "tanaka")["hr_max"]
        gellish = physiology.estimate_hr_max(30, "M", "gellish")["hr_max"]
        self.assertLess(abs(tanaka - gellish), 5)

    def test_cooper_matches_reference(self):
        # 3 000 m au test de Cooper ≈ 55,8 ml/kg/min
        self.assertAlmostEqual(physiology.vo2max_cooper(3000), 55.8, delta=0.5)

    def test_energy_from_power_matches_rule_of_thumb(self):
        """Au rendement de 23,5 %, 1 kJ ≈ 1 kcal (règle du cycliste)."""
        self.assertAlmostEqual(physiology.energy_from_power(1000), 1000, delta=25)

    def test_altitude_penalty(self):
        self.assertEqual(physiology.altitude_vo2max_factor(1000), 1.0)
        self.assertLess(physiology.altitude_vo2max_factor(2500), 0.92)

    def test_heat_penalty_grows_with_temperature(self):
        self.assertEqual(physiology.heat_pace_penalty(10), 0.0)
        self.assertLess(physiology.heat_pace_penalty(20),
                        physiology.heat_pace_penalty(30))

    def test_carb_needs_scale_with_duration(self):
        self.assertEqual(physiology.carb_needs(1800)["g_per_hour"], 0)
        self.assertGreaterEqual(physiology.carb_needs(14400)["g_per_hour"], 80)


class TestRisk(unittest.TestCase):
    def _rows(self, **overrides):
        base = {"date": "2026-01-01", "load": 80, "ctl": 60, "atl": 70, "tsb": -10,
                "acwr_ewma": 1.0, "acwr_rolling": 1.0, "monotony": 1.4,
                "strain": 3000, "ctl_ramp_7d": 3.0}
        base.update(overrides)
        return [dict(base, date=f"2026-01-{d:02d}") for d in range(1, 29)]

    def test_no_alerts_on_healthy_profile(self):
        alerts = risk.evaluate({"id": 1}, self._rows(), [], [])
        self.assertEqual([a for a in alerts if a["severity"] == "critical"], [])

    def test_high_acwr_is_critical(self):
        alerts = risk.evaluate({"id": 1}, self._rows(acwr_ewma=1.7), [], [])
        codes = {a["code"]: a for a in alerts}
        self.assertIn("acwr_high", codes)
        self.assertEqual(codes["acwr_high"]["severity"], "critical")
        self.assertEqual(codes["acwr_high"]["value"], 1.7)

    def test_monotony_alert(self):
        alerts = risk.evaluate({"id": 1}, self._rows(monotony=2.5), [], [])
        self.assertIn("monotony_high", {a["code"] for a in alerts})

    def test_open_injury_raises_alert(self):
        alerts = risk.evaluate({"id": 1}, self._rows(), [],
                               [{"status": "ouverte", "body_part": "genou",
                                 "date": "2026-01-05", "type": "tendinopathie",
                                 "side": "gauche", "severity": 3}])
        self.assertIn("injury_open", {a["code"] for a in alerts})

    def test_summary_reports_worst_severity(self):
        alerts = risk.evaluate({"id": 1}, self._rows(acwr_ewma=1.8, monotony=2.5), [], [])
        self.assertEqual(risk.summarize(alerts)["overall"], "critical")


if __name__ == "__main__":
    unittest.main(verbosity=2)
