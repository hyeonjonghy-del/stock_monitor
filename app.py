"""
국내 증시 투자자별 매매 모니터링 툴 v4
────────────────────────────────────────────────────────
실행: streamlit run app.py
필요: pip install --upgrade pykrx streamlit pandas
────────────────────────────────────────────────────────
"""

import os
import sys
import importlib
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

# ─── 페이지 설정 ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="📊 투자자별 매매 모니터링",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .stTabs [data-baseweb="tab"] { font-size: 15px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ─── KRX 로그인 처리 ──────────────────────────────────────────────────────────
def try_krx_login(krx_id: str, krx_pw: str) -> tuple[bool, str]:
    """KRX 로그인 시도. (성공여부, 메시지) 반환"""
    # 환경변수 설정
    os.environ["KRX_ID"] = krx_id
    os.environ["KRX_PW"] = krx_pw

    try:
        # pykrx 내부 auth 모듈로 로그인 시도 (v1.2.6+)
        from pykrx.website.comm.auth import build_krx_session, set_auth_session
        import pykrx.website.comm.webio as webio

        session = build_krx_session(krx_id, krx_pw)
        if session and session.is_authenticated:
            set_auth_session(session)
            webio._session = session
            return True, "✅ 로그인 성공"
        else:
            return False, "❌ 로그인 실패 — ID/PW를 확인하세요"

    except ImportError:
        # 구버전 pykrx — auth 모듈 없음
        return False, (
            "❌ pykrx 버전이 낮습니다.\n\n"
            "터미널에서 아래 명령어를 실행 후 앱을 재시작하세요:\n\n"
            "```\npip install --upgrade pykrx\n```"
        )
    except Exception as e:
        return False, f"❌ 오류: {e}"


# ─── 사이드바 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 검색 조건")

    with st.expander("🔐 KRX 로그인 (필수)", expanded=True):
        st.markdown(
            "[data.krx.co.kr](https://data.krx.co.kr) 무료 회원가입 후 입력"
        )
        krx_id = st.text_input("KRX 아이디", placeholder="아이디")
        krx_pw = st.text_input("KRX 비밀번호", type="password", placeholder="비밀번호")

        if st.button("🔓 로그인", key="btn_login"):
            if not krx_id or not krx_pw:
                st.warning("아이디와 비밀번호를 입력하세요.")
            else:
                with st.spinner("로그인 중..."):
                    ok, msg = try_krx_login(krx_id, krx_pw)
                    st.session_state["krx_ok"] = ok
                    st.session_state["krx_msg"] = msg

        # 상태 표시
        if st.session_state.get("krx_ok"):
            st.success("🟢 로그인됨")
            if st.button("🔄 캐시 초기화", key="btn_clear",
                         help="로그인 후에도 데이터가 안 나올 때 클릭"):
                st.cache_data.clear()
                st.toast("✅ 캐시 초기화 완료! 검색을 다시 실행하세요.")
        else:
            msg = st.session_state.get("krx_msg", "")
            if msg:
                st.error(msg)
            else:
                st.warning("🔴 미로그인")

    st.divider()
    selected_markets = st.multiselect(
        "📍 대상 시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"]
    )
    if not selected_markets:
        selected_markets = ["KOSPI"]

    st.divider()
    st.subheader("🔄 연속 순매수")
    n_days           = st.slider("연속 일수", 2, 7, 3)
    chk_foreign      = st.checkbox("외국인", value=True)
    chk_inst         = st.checkbox("기관합계", value=True)
    require_both     = st.checkbox("외국인·기관 동시 충족", value=True)
    top_n_candidates = st.slider("후보 종목 수 (TOP N)", 30, 200, 100)

    st.divider()
    st.subheader("📈 거래량 급증")
    vol_window  = st.slider("비교 기간 (거래일)", 5, 20, 10)
    vol_mult    = st.slider("급증 배율", 1.2, 5.0, 1.5, 0.1)
    min_vol_amt = st.number_input("최소 거래대금 (억원)", 0, 1000, 30, 10)

    st.divider()
    st.subheader("🌏 외국인 지분율")
    ratio_days       = st.slider("비교 기간 (거래일)", 1, 10, 3)
    ratio_change_min = st.slider("최소 변화 (%p)", 0.1, 3.0, 0.3, 0.1)

    st.divider()
    st.subheader("⚔️ 개미 역행")
    indiv_sell_min = st.number_input("개인 최소 순매도 (억원)", -5000, -1, -10)
    both_or_either = st.radio("기관·외인 조건", ["둘 다 순매수", "하나라도 순매수"])

    st.divider()
    show_debug = st.checkbox("🔧 디버그 정보 표시", False)


# ─── 로그인 전 안내 화면 ────────────────────────────────────────────────────────
if not st.session_state.get("krx_ok"):
    st.title("📊 국내 증시 투자자별 매매 모니터링")
    st.info("""
    ### 🔐 KRX 로그인 후 사용 가능합니다

    **pykrx 1.2.6부터 KRX 로그인이 필수입니다.**

    **① pykrx 최신 버전 설치** (처음 한 번만)
    ```
    pip install --upgrade pykrx
    ```

    **② KRX 계정 만들기** (무료)  
    → [data.krx.co.kr](https://data.krx.co.kr) → 우측 상단 **회원가입**

    **③ 왼쪽 사이드바에 아이디 / 비밀번호 입력 → 로그인**
    """)
    st.stop()


# ─── 로그인 후: pykrx import ───────────────────────────────────────────────────
from pykrx import stock


# ─── 유틸 ─────────────────────────────────────────────────────────────────────
def get_business_days(n: int) -> list:
    days = []
    d = datetime.today()
    while len(days) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            days.append(d.strftime("%Y%m%d"))
    return list(reversed(days))

def color_signed(val):
    try:
        v = float(val)
        if v > 0: return "color:#d73027;font-weight:bold"
        if v < 0: return "color:#1a6bb5;font-weight:bold"
    except: pass
    return ""


# ─── 캐시된 API 호출 ──────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_top_net_buy(fd, td, mkt, inv):
    try:
        df = stock.get_market_net_purchases_of_equities_by_ticker(fd, td, mkt, inv)
        return df if not df.empty else pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_daily_investor(fd, td, ticker):
    try:
        return stock.get_market_trading_value_by_date(fd, td, ticker, on="순매수", detail=False)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_ohlcv_day(date, mkt):
    try:
        return stock.get_market_ohlcv_by_ticker(date, mkt)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ticker_name_map(date: str, market: str) -> dict:
    """티커 → 종목명 매핑 딕셔너리 (전체 시장)"""
    try:
        tickers = stock.get_market_ticker_list(date, market=market)
        return {t: stock.get_market_ticker_name(t) for t in tickers}
    except:
        return {}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_foreign_ratio(date, mkt):
    try:
        return stock.get_exhaustion_rates_of_foreign_investment_by_ticker(date, mkt)
    except:
        return pd.DataFrame()


# ─── 날짜 ─────────────────────────────────────────────────────────────────────
days_list   = get_business_days(max(n_days, vol_window + 1, ratio_days + 1) + 3)
latest_day  = days_list[-1]
n_day_start = days_list[-n_days]

st.title("📊 국내 증시 투자자별 매매 모니터링")
st.caption(
    f"📅 기준: **{latest_day[:4]}.{latest_day[4:6]}.{latest_day[6:]}** | "
    f"pykrx (KRX 공식) | 30분 캐시"
)

tab1, tab2, tab3, tab4 = st.tabs([
    "🔄 N일 연속 순매수",
    "📈 거래량 급증",
    "🌏 외국인 지분율 급변",
    "⚔️ 개미 역행 종목",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — N일 연속 순매수
# ═══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader(f"외국인·기관 {n_days}일 연속 순매수 종목")
    with st.expander("ℹ️ 검색 방식"):
        st.markdown(f"**2단계**: 기간 합산 TOP {top_n_candidates} 추출 → 일별 연속성 검증  ⏱️ 1~2분 소요")

    investors = []
    if chk_foreign: investors.append("외국인")
    if chk_inst:    investors.append("기관합계")
    inv_col_map = {"외국인": "외국인합계", "기관합계": "기관합계"}

    if not investors:
        st.warning("외국인 또는 기관합계 중 하나 이상 선택하세요.")
    elif st.button("🔍 검색 실행", key="run1", type="primary"):
        all_results = []
        dbg = []

        for mkt in selected_markets:
            candidates = set()
            name_map = {}
            cand_dfs = {}

            for inv in investors:
                df = fetch_top_net_buy(n_day_start, latest_day, mkt, inv)
                dbg.append(f"[{mkt}][{inv}] TOP종목: {len(df)}개")
                if not df.empty:
                    candidates.update(df.index[:top_n_candidates].tolist())
                    if "종목명" in df.columns:
                        name_map.update(df["종목명"].to_dict())
                    cand_dfs[inv] = df

            dbg.append(f"[{mkt}] 합산 후보: {len(candidates)}개")
            if not candidates:
                st.warning(f"⚠️ {mkt}: 후보 종목 없음 — 로그인·날짜 확인 필요")
                continue

            pb = st.empty()
            passed = []
            for i, ticker in enumerate(candidates):
                pb.text(f"[{mkt}] {i+1}/{len(candidates)} 검증 중... {ticker}")
                daily = fetch_daily_investor(n_day_start, latest_day, ticker)
                if daily.empty or len(daily) < n_days:
                    continue
                check_cols = [inv_col_map[inv] for inv in investors
                              if inv_col_map.get(inv) in daily.columns]
                if not check_cols:
                    continue
                ok = (
                    (daily[check_cols].iloc[-n_days:] > 0).all().all()
                    if require_both and len(check_cols) == len(investors)
                    else (daily[check_cols].iloc[-n_days:] > 0).any(axis=1).all()
                )
                if ok:
                    row = {"시장": mkt, "티커": ticker, "종목명": name_map.get(ticker, "")}
                    for col in check_cols:
                        row[f"{col}(억)"] = round(daily[col].iloc[-n_days:].sum() / 1e8, 1)
                    try:
                        oc = fetch_ohlcv_day(latest_day, mkt)
                        if not oc.empty and ticker in oc.index and "등락률" in oc.columns:
                            row["등락률(%)"] = oc.loc[ticker, "등락률"]
                    except: pass
                    passed.append(row)
            pb.empty()
            dbg.append(f"[{mkt}] 통과: {len(passed)}개")
            all_results.extend(passed)

        if show_debug:
            st.info("🔧 " + " | ".join(dbg))

        if all_results:
            final = pd.DataFrame(all_results)
            num_cols = [c for c in final.columns if "억" in c or "%" in c]
            for c in num_cols:
                final[c] = pd.to_numeric(final[c], errors="coerce")
            sc = next((c for c in final.columns if "억" in c), None)
            if sc: final = final.sort_values(sc, ascending=False)
            st.success(f"✅ **{len(final)}개 종목** 발견")
            st.dataframe(final.style.applymap(color_signed, subset=num_cols),
                         use_container_width=True, height=480)
            st.download_button("📥 CSV", final.to_csv(index=False, encoding="utf-8-sig").encode(),
                               f"연속순매수_{n_days}일.csv", "text/csv")
        else:
            st.info("📭 조건에 맞는 종목이 없습니다. 연속 일수를 줄이거나 조건을 완화해보세요.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — 거래량 급증
# ═══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("거래량 급증 종목")
    st.markdown(f"> 직전 {vol_window}거래일 평균 대비 **{vol_mult}배 이상** & 거래대금 **{min_vol_amt}억 이상**")

    if st.button("🔍 검색 실행", key="run2", type="primary"):
        target_days = days_list[-(vol_window + 1):]
        avg_days    = target_days[:-1]
        last_day    = target_days[-1]
        results     = []
        pb = st.progress(0)
        total = len(selected_markets) * (vol_window + 1)
        step  = 0

        for mkt in selected_markets:
            vol_by_day = {}
            for day in target_days:
                step += 1
                pb.progress(step / total, text=f"{mkt} | {day}")
                df = fetch_ohlcv_day(day, mkt)
                if not df.empty and "거래량" in df.columns:
                    vol_by_day[day] = df["거래량"]

            avg_frames = [vol_by_day[d] for d in avg_days if d in vol_by_day]
            if not avg_frames: continue
            avg_vol = pd.concat(avg_frames, axis=1).mean(axis=1)
            lo = fetch_ohlcv_day(last_day, mkt)
            if lo.empty: continue

            lo = lo.copy()
            lo["평균거래량"]   = avg_vol
            lo["급증배율"]    = (lo["거래량"] / lo["평균거래량"].replace(0, np.nan)).round(2)
            lo["거래대금(억)"] = (lo["거래대금"] / 1e8).round(1)
            mask = (lo["급증배율"] >= vol_mult) & (lo["거래대금(억)"] >= min_vol_amt)
            f    = lo[mask].copy()
            f.insert(0, "시장", mkt)
            f.index.name = "티커"
            results.append(f.reset_index())

        pb.empty()
        if results:
            final = pd.concat(results, ignore_index=True).sort_values("급증배율", ascending=False)
            # 종목명이 없으면 시장별 매핑으로 추가
            if "종목명" not in final.columns or final["종목명"].isna().all():
                name_map = {}
                for mkt in selected_markets:
                    name_map.update(fetch_ticker_name_map(last_day, mkt))
                final["종목명"] = final["티커"].map(name_map).fillna("")
            show  = ["시장","티커","종목명","거래량","평균거래량","급증배율","거래대금(억)","등락률"]
            show  = [c for c in show if c in final.columns]
            st.success(f"✅ **{len(final)}개 종목** 발견")
            c1, c2, c3 = st.columns(3)
            c1.metric("종목 수", f"{len(final)}개")
            c2.metric("최고 배율", f"{final['급증배율'].max():.1f}x")
            c3.metric("평균 배율", f"{final['급증배율'].mean():.1f}x")
            st.dataframe(
                final[show].style
                    .applymap(color_signed, subset=["등락률"])
                    .background_gradient(subset=["급증배율"], cmap="YlOrRd"),
                use_container_width=True, height=480
            )
            st.download_button("📥 CSV", final.to_csv(index=False, encoding="utf-8-sig").encode(),
                               "거래량급증.csv", "text/csv")
        else:
            st.info("📭 조건에 맞는 종목이 없습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — 외국인 지분율 급변
# ═══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("외국인 지분율 급변")
    st.markdown(f"> {ratio_days}거래일 사이 지분율 **±{ratio_change_min}%p 이상** 변화")

    if st.button("🔍 검색 실행", key="run3", type="primary"):
        target_days = days_list[-(ratio_days + 1):]
        old_day, new_day = target_days[0], target_days[-1]
        results = []
        pb = st.progress(0)
        for i, (day, label) in enumerate([(old_day,"과거"), (new_day,"현재")]):
            pb.progress((i+1) / (len(selected_markets)*2))
            for mkt in selected_markets:
                pass
        pb.empty()

        pb = st.progress(0)
        total = len(selected_markets) * 2
        step  = 0
        for mkt in selected_markets:
            step += 1; pb.progress(step/total, text=f"{mkt} | {old_day}...")
            df_old = fetch_foreign_ratio(old_day, mkt)
            step += 1; pb.progress(step/total, text=f"{mkt} | {new_day}...")
            df_new = fetch_foreign_ratio(new_day, mkt)
            if df_old.empty or df_new.empty:
                st.warning(f"{mkt}: 지분율 데이터 없음")
                continue
            merged = df_old[["지분율"]].join(
                df_new[["지분율"]].rename(columns={"지분율":"지분율_현재"}), how="inner"
            ).rename(columns={"지분율":"지분율_과거"})
            merged["지분율변화(%p)"] = (merged["지분율_현재"] - merged["지분율_과거"]).round(2)
            f = merged[merged["지분율변화(%p)"].abs() >= ratio_change_min].copy()
            f["방향"] = f["지분율변화(%p)"].apply(lambda x: "▲ 매수" if x>0 else "▼ 매도")
            f.insert(0, "시장", mkt); f.index.name = "티커"
            results.append(f.reset_index())
        pb.empty()

        if results:
            final = pd.concat(results, ignore_index=True)
            final = final.sort_values("지분율변화(%p)", key=abs, ascending=False)
            # 종목명 추가
            if "종목명" not in final.columns:
                name_map = {}
                for mkt in selected_markets:
                    name_map.update(fetch_ticker_name_map(old_day, mkt))
                final.insert(1, "종목명", final["티커"].map(name_map).fillna(""))
            st.success(f"✅ **{len(final)}개** (증가 {(final['지분율변화(%p)']>0).sum()}, "
                       f"감소 {(final['지분율변화(%p)']<0).sum()})")
            st.dataframe(final.style.applymap(color_signed, subset=["지분율변화(%p)"]),
                         use_container_width=True, height=480)
            st.download_button("📥 CSV", final.to_csv(index=False, encoding="utf-8-sig").encode(),
                               "외국인지분율.csv", "text/csv")
        else:
            st.info("📭 조건에 맞는 종목이 없습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — 개미 역행
# ═══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("개미 역행 종목")
    st.markdown(
        f"> 개인 **{indiv_sell_min:,}억 이상** 순매도 & "
        f"기관·외인 {'**둘 다**' if '둘 다' in both_or_either else '**하나라도**'} 순매수"
    )

    if st.button("🔍 검색 실행", key="run4", type="primary"):
        results = []
        pb = st.progress(0)
        total = len(selected_markets) * 3
        step  = 0

        for mkt in selected_markets:
            dfs = {}
            for inv in ["개인", "외국인", "기관합계"]:
                step += 1
                pb.progress(step/total, text=f"{mkt} | {inv}...")
                dfs[inv] = fetch_top_net_buy(latest_day, latest_day, mkt, inv)

            if any(df.empty for df in dfs.values()):
                st.warning(f"{mkt}: 일부 데이터 없음")
                continue

            merged = (
                dfs["개인"][["순매수거래대금"]]
                .rename(columns={"순매수거래대금":"개인_순매수"})
                .join(dfs["외국인"][["순매수거래대금"]].rename(columns={"순매수거래대금":"외국인_순매수"}), how="inner")
                .join(dfs["기관합계"][["순매수거래대금"]].rename(columns={"순매수거래대금":"기관_순매수"}), how="inner")
            )

            threshold = indiv_sell_min * 1e8
            imask = merged["개인_순매수"] <= threshold
            vmask = (
                (merged["외국인_순매수"] > 0) & (merged["기관_순매수"] > 0)
                if "둘 다" in both_or_either
                else (merged["외국인_순매수"] > 0) | (merged["기관_순매수"] > 0)
            )
            f = merged[imask & vmask].copy()
            for col, lbl in [("개인_순매수","개인(억)"),("외국인_순매수","외국인(억)"),("기관_순매수","기관(억)")]:
                f[lbl] = (f[col] / 1e8).round(1)
            f.insert(0, "시장", mkt); f.index.name = "티커"
            results.append(f.reset_index())

        pb.empty()
        if results:
            final = pd.concat(results, ignore_index=True).sort_values("개인(억)", ascending=True)
            # 종목명 추가
            if "종목명" not in final.columns:
                name_map = {}
                for mkt in selected_markets:
                    name_map.update(fetch_ticker_name_map(latest_day, mkt))
                final.insert(2, "종목명", final["티커"].map(name_map).fillna(""))
            num   = [c for c in ["개인(억)","외국인(억)","기관(억)"] if c in final.columns]
            show  = ["시장","티커","종목명"] + num
            st.success(f"✅ **{len(final)}개 종목** 발견")
            st.dataframe(final[show].style.applymap(color_signed, subset=num),
                         use_container_width=True, height=480)
            st.download_button("📥 CSV", final.to_csv(index=False, encoding="utf-8-sig").encode(),
                               "개미역행.csv", "text/csv")
        else:
            st.info("📭 조건에 맞는 종목이 없습니다.")


st.divider()
st.caption("📌 pykrx (KRX 공식) | 장 마감(15:30) 후 당일 데이터 확정 | 30분 캐시")