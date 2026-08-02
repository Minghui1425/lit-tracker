"""--catchup 的周期判断。

这是定时任务能不能「关机错过后补上、但又不天天重跑」的全部依据，
边界（正好是运行日当天、跨周、坏标记）必须钉死。
"""
import datetime

import cli

MON, TUE, WED, THU, SUN = (datetime.date(2026, 8, 3), datetime.date(2026, 8, 4),
                           datetime.date(2026, 8, 5), datetime.date(2026, 8, 6),
                           datetime.date(2026, 8, 9))
LAUNCHD_TUE = 2          # plist 的 Weekday 口径：0=周日 … 6=周六
WEEK = datetime.timedelta(days=7)


def test_period_starts_on_the_scheduled_weekday():
    for day in (TUE, WED, THU, SUN):
        assert cli._period_start(day, LAUNCHD_TUE) == TUE
    assert cli._period_start(MON, LAUNCHD_TUE) == TUE - WEEK   # 运行日前一天属上一周期


def test_sunday_anchor():
    assert cli._period_start(WED, 0) == datetime.date(2026, 8, 2)
    assert cli._period_start(datetime.date(2026, 8, 2), 0) == datetime.date(2026, 8, 2)


def _write(tmp_path, day, tag="weekly"):
    (tmp_path / f".last_run_{tag}").write_text(day.isoformat(), encoding="utf-8")


def test_no_marker_means_run(tmp_path):
    assert cli._catchup_skip(tmp_path, "weekly", LAUNCHD_TUE, THU) is False


def test_skips_when_already_ran_this_period(tmp_path):
    _write(tmp_path, TUE)
    assert cli._catchup_skip(tmp_path, "weekly", LAUNCHD_TUE, THU) is True
    # 同一周期内反复登录，也只跑那一次
    assert cli._catchup_skip(tmp_path, "weekly", LAUNCHD_TUE, SUN) is True


def test_runs_when_last_run_was_a_previous_period(tmp_path):
    """关机错过一整周：下次登录必须补跑。"""
    _write(tmp_path, TUE - WEEK)
    assert cli._catchup_skip(tmp_path, "weekly", LAUNCHD_TUE, THU) is False


def test_manual_run_before_the_scheduled_day_does_not_swallow_it(tmp_path):
    """上周日手动跑过，本周二的定时任务照跑——手动跑属于上一周期。"""
    _write(tmp_path, SUN - WEEK)
    assert cli._catchup_skip(tmp_path, "weekly", LAUNCHD_TUE, TUE) is False


def test_corrupt_marker_means_run(tmp_path):
    (tmp_path / ".last_run_weekly").write_text("上周二", encoding="utf-8")
    assert cli._catchup_skip(tmp_path, "weekly", LAUNCHD_TUE, THU) is False


def test_mark_and_read_roundtrip(tmp_path):
    cli._mark_ran(tmp_path, "citations")
    today = datetime.date.today()
    assert (tmp_path / ".last_run_citations").read_text(encoding="utf-8") == today.isoformat()
    assert cli._catchup_skip(tmp_path, "citations", LAUNCHD_TUE, today) is True


def test_tasks_have_separate_markers(tmp_path):
    cli._mark_ran(tmp_path, "weekly")
    assert cli._catchup_skip(tmp_path, "citations", LAUNCHD_TUE, THU) is False


def test_marker_dir_is_created_if_missing(tmp_path):
    out = tmp_path / "output"                 # 首次运行时 output/ 还不存在
    cli._mark_ran(out, "weekly")
    assert (out / ".last_run_weekly").exists()
