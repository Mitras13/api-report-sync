"""WTX_PT / DCU_PT در برابر مشخصات کاربر (۲۰۲۶-۱۱-۱۶)، با API ساختگی - بدون شبکه."""
import io
import json

import jdatetime
import pandas as pd
import pytest

from downloaders import pezeshket_core as core, WTX_PT, DCU_PT


class Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code, self._payload, self.content = status, payload, content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "TOKEN_FILE", tmp_path / "tokenPT.txt")
    monkeypatch.setattr(core, "CREDENTIALS_FILE", tmp_path / "credentialsPT.txt")
    monkeypatch.setattr(core, "CSV_ROOT", tmp_path / "csv")
    monkeypatch.setattr(core, "RETRY_DELAY_SECONDS", 0)
    import downloaders.downloader_core as dc
    monkeypatch.setattr(dc, "RAW_DATA_ROOT", tmp_path / "raw")
    for k in ("PT_USERNAME", "PT_PASSWORD", "PT_CLIENT_ID"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "credentialsPT.txt").write_text(json.dumps({"username": "u", "password": "p", "client_id": "c"}))
    return tmp_path


DAY_START = jdatetime.datetime(1405, 8, 24, 0, 0, 0)
DAY_END = jdatetime.datetime(1405, 8, 24, 23, 59, 59)
MS_IN_DAY = (int(DAY_START.togregorian().replace(tzinfo=core.TEHRAN).timestamp()) + 3600) * 1000  # 01:00 تهران


def test_unix_timestamp_is_tehran():
    # 1405/08/24 = 2026-11-15؛ تهران +03:30
    assert core.api_unix_timestamp(DAY_START) == 1794688200  # 2026-11-14T20:30:00Z
    assert core.api_unix_timestamp(DAY_END) - core.api_unix_timestamp(DAY_START) == 86399


def test_wtx_spec(env, monkeypatch):
    calls = {"login": 0, "pages": [], "bulk": []}
    history = [
        {"reason": "شارژ کیف پول", "amount": 1000000, "userId": "u1", "gateway": "zarinpal", "createdAt": MS_IN_DAY,
         "reasonMetadata": {"status": "SETTLED"},
         "gatewayFailReason": {"code": 17, "response": {"amount": 5, "state": "CanceledByUser"}}},
        {"reason": "هزینه جلسه مشاوره", "amount": 200, "userId": "a1", "createdAt": MS_IN_DAY,
         "reasonMetadata": {"adviserId": "a1", "status": "WEIRD"}},
        {"reason": "x", "amount": 1, "userId": "ghost", "createdAt": MS_IN_DAY},  # بدون کلیدهای اختیاری
    ]

    def fake_post(url, data=None, timeout=None):
        calls["login"] += 1
        assert data["grant_type"] == "password" and data["client_id"] == "c" and timeout == 60
        return Resp(payload={"access_token": "T2"})

    def fake_request(method, url, headers=None, timeout=None, params=None, json=None):
        assert timeout == 60
        if headers["Authorization"] == "Bearer OLD":
            return Resp(401)
        if url == WTX_PT.URL:
            assert "reason" not in params and params["limit"] == 100
            calls["pages"].append(params["offset"])
            i = params["offset"] // 100
            return Resp(payload={"history": history[i * 2:(i + 1) * 2], "pages": 2})
        calls["bulk"].append(json["ids"])
        return Resp(payload={"users": [
            {"user": {"userId": "u1", "nickname": "علی", "avatar": {"initials": "\ud835F"}}, "userType": "USER",
             "nationalCode": "123"},
            {"user": {"userId": "a1", "nickname": "مشاور یک"}, "userType": "ADVISER"}]})

    monkeypatch.setattr(core.requests, "post", fake_post)
    monkeypatch.setattr(core.requests, "request", fake_request)
    core.TOKEN_FILE.write_text("OLD")

    result = WTX_PT.fetch(None, DAY_START, DAY_END)
    assert calls["login"] == 1 and core.TOKEN_FILE.read_text() == "T2"
    assert calls["pages"] == [0, 100]
    assert calls["bulk"] == [["u1", "a1", "ghost"]]

    df = pd.read_parquet(result["path"])
    assert list(df.columns) == WTX_PT.WTX_COLUMNS and len(WTX_PT.WTX_COLUMNS) == 25
    r0, r1, r2 = df.to_dict("records")
    assert r0["reason"] == "شارژ کیف پول" and r0["amount"] == 1000000 and r0["nickname"] == "علی"
    assert r0["createdAt"] == "1405/08/24 01:00:00"
    assert (r0["status"], r0["failedReason"], r0["gatewayFailCode"], r0["failedAmount"]) == ("تکمیل شده", "لغو توسط کاربر", 17, 5)
    assert r0["userNationalCode"] is None and r0["userAvatarInitials"] is None  # داده‌ی شخصی ذخیره نمی‌شود
    assert r1["advisorName"] == "مشاور یک" and r1["advisorUserType"] == "ADVISER" and r1["status"] == "WEIRD"
    assert r2["nickname"] is None and r2["gateway"] is None and r2["status"] is None

    csvs = list((env / "csv" / "WTX" / "PT").glob("*.csv"))
    assert len(csvs) == 1 and csvs[0].name.startswith("PT_WTX_140508240000_140508242359_")
    assert csvs[0].read_bytes().startswith(b"\xef\xbb\xbf")
    assert list(pd.read_csv(csvs[0], encoding="utf-8-sig").columns) == WTX_PT.WTX_COLUMNS


def test_wtx_empty_day_and_second_401(env, monkeypatch):
    monkeypatch.setattr(core.requests, "request",
                        lambda *a, **k: Resp(payload={"history": [], "pages": 0}))
    core.TOKEN_FILE.write_text("T")
    df = pd.read_parquet(WTX_PT.fetch(None, DAY_START, DAY_END)["path"])
    assert len(df) == 0 and list(df.columns) == WTX_PT.WTX_COLUMNS

    tries = []
    monkeypatch.setattr(core.requests, "post", lambda *a, **k: Resp(payload={"access_token": "NEW"}))
    monkeypatch.setattr(core.requests, "request", lambda *a, **k: tries.append(1) or Resp(403))
    with pytest.raises(core.AuthExpiredError):
        WTX_PT.fetch(None, DAY_START, DAY_END)
    assert len(tries) == 2  # یک بار + یک بار بعد از لاگین، بدون retry


def test_server_errors_retry_three_times(env, monkeypatch):
    tries = []
    monkeypatch.setattr(core.requests, "request", lambda *a, **k: tries.append(1) or Resp(502))
    core.TOKEN_FILE.write_text("T")
    with pytest.raises(core.ServerHTTPError):
        WTX_PT.fetch(None, DAY_START, DAY_END)
    assert len(tries) == 3


def test_dcu_spec(env, monkeypatch):
    cols = ["شناسه", "عنوان", "کد", "نوع", "مبلغ", "تخفیف", "زمان مصرف", "نوع مشاوره", "مبلغ کل", "قابل پرداخت",
            "شناسه کاربر", "کاربر", "شماره همراه کاربر", "مشاور", "شماره همراه مشاور", "تخصص"]
    buf = io.BytesIO()
    pd.DataFrame([[1, " کد تخفیف یلدا ", "YALDA", "درصدی", 100, 20, "1405/08/24 10:00:00", "تلفنی", 100, 80,
                   "u1", "علی", "0912", "دکتر", "0935", "روانشناس"]], columns=cols).to_excel(buf, index=False)
    seen = {}

    def fake_request(method, url, headers=None, timeout=None, params=None, json=None):
        seen.update(params)
        return Resp(content=buf.getvalue())

    monkeypatch.setattr(core.requests, "request", fake_request)
    core.TOKEN_FILE.write_text("T")
    df = pd.read_parquet(DCU_PT.fetch(None, DAY_START, DAY_END)["path"])
    assert seen["exportFileType"] == "EXCEL" and seen["expLimit"] == 100000
    assert list(df.columns) == cols
    assert df.loc[0, "عنوان"] == " کد تخفیف یلدا " and df.loc[0, "مشاور"] == "دکتر"
    assert df.loc[0, "شماره همراه کاربر"] is None

    monkeypatch.setattr(core.requests, "request", lambda *a, **k: Resp(content=b"<html>error</html>"))
    with pytest.raises(core.InvalidResponseError):
        DCU_PT.fetch(None, DAY_START, DAY_END)
