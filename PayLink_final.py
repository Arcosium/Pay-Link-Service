from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import pandas as pd
import json
import re
import os
import urllib.request
from dotenv import load_dotenv

# ============================================
# 설정
# ============================================
load_dotenv("/home/opc/projects/.env")  # 통합 .env (전 프로젝트 공용)
CSV_PATH = os.environ.get("CSV_PATH", "plans.csv")
LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "").rstrip("/")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "Qwen3.6-35B-A3B-Uncensored-Claude-Genesis-Q8_0.gguf")

def local_llm_completion(prompt: str) -> str:
    if not LOCAL_LLM_BASE_URL:
        raise RuntimeError("LOCAL_LLM_BASE_URL is not configured")
    payload = {"model": LOCAL_LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
    req = urllib.request.Request(LOCAL_LLM_BASE_URL + "/chat/completions", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read())["choices"][0]["message"]["content"]

app = FastAPI(title="PayLink API", version="2.0")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.get("/", include_in_schema=False)
def serve_index():
    index_path = os.path.join(_BASE_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")
    return {"detail": "index.html not found", "endpoints": ["/chat", "/health", "/docs"]}

# ============================================
# 데이터 로드
# ============================================
df_plans = pd.DataFrame()

def load_plans_data():
    global df_plans
    try:
        print(f"[DATA] 현재 디렉토리: {os.getcwd()}")
        
        # CSV_PATH가 절대 경로가 아니면 현재 스크립트 파일의 디렉토리를 기준으로 함
        if not os.path.isabs(CSV_PATH):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            full_csv_path = os.path.join(script_dir, CSV_PATH)
        else:
            full_csv_path = CSV_PATH

        if os.path.exists(full_csv_path):
            df_plans = pd.read_csv(full_csv_path)
            df_plans['monthly_fee'] = pd.to_numeric(
                df_plans['monthly_fee'].astype(str).str.replace(',', ''), 
                errors='coerce'
            ).fillna(0)
            df_plans['data_gb'] = pd.to_numeric(df_plans['data_gb'], errors='coerce').fillna(0)
            df_plans['voice_min'] = pd.to_numeric(df_plans['voice_min'], errors='coerce').fillna(0)
            df_plans['sms_count'] = pd.to_numeric(df_plans['sms_count'], errors='coerce').fillna(0)
            print(f"✅ 요금제 데이터 로드 완료: {len(df_plans)}개")
            print(f"[DATA] 가격 범위: {int(df_plans['monthly_fee'].min())} ~ {int(df_plans['monthly_fee'].max())}원")
        else:
            print(f"❌ {full_csv_path} 파일 없음!")
    except Exception as e:
        print(f"❌ 데이터 로드 실패: {e}")

load_plans_data()

# ============================================
# Pydantic 모델
# ============================================
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    success: bool
    messages: List[Dict[str, Any]]
    error: Optional[str] = None

# ============================================
# 개선된 의도 분석 프롬프트
# ============================================
INTENT_PROMPT_TEMPLATE = """당신은 휴대폰 요금제 상담 챗봇의 의도 분석기입니다.
사용자 메시지를 분석하여 JSON 형식으로 응답하세요.

## 분석 규칙

### 1. is_plan_query (boolean)
다음 키워드가 포함되면 true:
- 요금제, 요금, 통신, 휴대폰, 핸드폰, 알뜰폰
- 데이터, 기가, GB, 무제한
- 만원, 원, 가격, 저렴, 싼
- 추천, 찾아, 알려, 있어, 뭐야
- 통화, 문자, SMS
- SKT, KT, LG, 알뜰
- 5G, LTE
- 네이버페이, 넷플릭스, 혜택, 할인

### 2. intent_type (string)
- "plan_search": 요금제를 찾거나 추천받으려는 의도
- "greeting": 인사 (안녕, 하이, 헬로 등)
- "chit_chat": 요금제와 무관한 잡담

### 3. params (object) - 요금제 검색 조건
- price_limit: 가격 상한 (숫자, 원 단위)
  - "1만원" → 10000
  - "2만원대" → 20000
  - "3만5천원" → 35000
  - "저렴한" → 20000 (기본값)
  
- data_gb: 필요 데이터량 (숫자, GB 단위)
  - "5기가" → 5
  - "10GB" → 10
  - "무제한" → 999
  - "많이" → 50
  
- benefit_keyword: 원하는 혜택 (문자열)
  - "넷플릭스", "네이버페이", "올리브영", "배달의민족" 등
  
- category: 통신망 종류
  - "5G" 또는 "LTE"

- exclude_discount: 할인 제외 여부 (boolean)
  - "할인 안 되는", "평생 요금", "가격 변동 없는", "계속 유지", "정상가만" 등의 표현이 있으면 true

조건이 명시되지 않은 필드는 생략하세요.

## 예시

입력: "안녕"
출력: {{"is_plan_query": false, "intent_type": "greeting", "params": {{}}}}

입력: "배고파"
출력: {{"is_plan_query": false, "intent_type": "chit_chat", "params": {{}}}}

입력: "요금제 추천해줘"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{}}}}

입력: "2만원대 요금제"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"price_limit": 20000}}}}

입력: "데이터 많고 싼 거"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"data_gb": 50, "price_limit": 20000}}}}

입력: "3만원 이하로 데이터 무제한"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"price_limit": 30000, "data_gb": 999}}}}

입력: "네이버페이 혜택 있는 요금제 찾아줘"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"benefit_keyword": "네이버페이"}}}}

입력: "5G 요금제 중에 2만원대"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"price_limit": 20000, "category": "5G"}}}}

입력: "1만5천원 이하 알뜰폰"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"price_limit": 15000}}}}

입력: "넷플릭스 되는 요금제"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"benefit_keyword": "넷플릭스"}}}}

입력: "제일 싼 요금제"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"price_limit": 15000}}}}

입력: "데이터 10기가 이상"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"data_gb": 10}}}}

입력: "할인 안 되는 요금제 알려줘"
출력: {{"is_plan_query": true, "intent_type": "plan_search", "params": {{"exclude_discount": true}}}}

## 분석할 메시지
"{message}"

## 응답 (JSON만 출력, 다른 텍스트 없이)
"""

def extract_intent(message: str) -> dict:
    """사용자 메시지에서 의도와 파라미터 추출"""
    
    prompt = INTENT_PROMPT_TEMPLATE.format(message=message)
    
    try:
        ai_raw = local_llm_completion(prompt).strip()
        print(f"[INTENT] AI 응답: {ai_raw[:200]}")
        
        # JSON 추출
        json_match = re.search(r'\{.*\}', ai_raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            print(f"[INTENT] 파싱 결과: {result}")
            return result
        
        # JSON 파싱 실패 시 키워드 기반 폴백
        print("[INTENT] JSON 파싱 실패, 키워드 폴백 사용")
        return keyword_fallback(message)
        
    except Exception as e:
        print(f"[INTENT] AI 오류: {e}, 키워드 폴백 사용")
        return keyword_fallback(message)


def keyword_fallback(message: str) -> dict:
    """AI 실패 시 키워드 기반 의도 분석"""
    
    msg_lower = message.lower()
    
    # 인사 체크
    greetings = ["안녕", "하이", "헬로", "반가워", "처음"]
    if any(g in msg_lower for g in greetings):
        return {"is_plan_query": False, "intent_type": "greeting", "params": {}}
    
    # 요금제 관련 키워드 체크
    plan_keywords = [
        "요금", "요금제", "추천", "찾아", "알려", "있어", "뭐야", "뭐있",
        "만원", "원", "가격", "싼", "저렴", "비싼",
        "데이터", "기가", "gb", "무제한",
        "통화", "문자", "sms",
        "통신", "휴대폰", "핸드폰", "알뜰폰", "알뜰",
        "skt", "kt", "lg", "sk",
        "5g", "lte",
        "혜택", "할인", "네이버", "넷플릭스", "올리브영"
    ]
    
    is_plan_query = any(kw in msg_lower for kw in plan_keywords)
    
    if not is_plan_query:
        return {"is_plan_query": False, "intent_type": "chit_chat", "params": {}}
    
    # 파라미터 추출
    params = {}
    
    # 가격 추출
    price_patterns = [
        (r'(\d+)\s*만\s*원대', lambda m: int(m.group(1)) * 10000),
        (r'(\d+)\s*만\s*(\d+)\s*천', lambda m: int(m.group(1)) * 10000 + int(m.group(2)) * 1000),
        (r'(\d+)\s*만원', lambda m: int(m.group(1)) * 10000),
        (r'(\d+)\s*만', lambda m: int(m.group(1)) * 10000),
        (r'(\d{4,})\s*원', lambda m: int(m.group(1))),
    ]
    
    for pattern, extractor in price_patterns:
        match = re.search(pattern, message)
        if match:
            params["price_limit"] = extractor(match)
            break
    
    # "저렴", "싼" 키워드
    if not params.get("price_limit") and any(w in msg_lower for w in ["저렴", "싼", "싸고"]):
        params["price_limit"] = 20000
    
    # 데이터 추출
    data_patterns = [
        (r'(\d+)\s*기가', lambda m: int(m.group(1))),
        (r'(\d+)\s*gb', lambda m: int(m.group(1))),
        (r'(\d+)\s*GB', lambda m: int(m.group(1))),
    ]
    
    for pattern, extractor in data_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            params["data_gb"] = extractor(match)
            break
    
    # "무제한", "많이" 키워드
    if "무제한" in msg_lower:
        params["data_gb"] = 999
    elif any(w in msg_lower for w in ["많이", "많은", "많고"]) and not params.get("data_gb"):
        params["data_gb"] = 50
    
    # 혜택 키워드
    benefits = ["네이버페이", "네이버", "넷플릭스", "올리브영", "배달의민족", "쿠팡", "유튜브", "할인"]
    for b in benefits:
        if b.lower() in msg_lower:
            params["benefit_keyword"] = b
            break
            
    # 카테고리 (5G/LTE)
    if "5g" in msg_lower:
        params["category"] = "5G"
    elif "lte" in msg_lower:
        params["category"] = "LTE"
        
    # 할인 제외
    if any(w in msg_lower for w in ["할인 안 되는", "평생 요금", "가격 변동 없는", "계속 유지", "정상가만"]):
        params["exclude_discount"] = True
        
    return {"is_plan_query": True, "intent_type": "plan_search", "params": params}


def search_plans(params: dict) -> pd.DataFrame:
    """파라미터에 따라 요금제 검색 및 필터링"""
    
    if df_plans.empty:
        return pd.DataFrame()
        
    filtered_df = df_plans.copy()
    
    # 가격 필터링
    if "price_limit" in params:
        filtered_df = filtered_df[filtered_df['monthly_fee'] <= params['price_limit']]
        
    # 데이터량 필터링
    if "data_gb" in params:
        # 무제한 요금제는 999로 가정
        if params['data_gb'] == 999:
            filtered_df = filtered_df[
                (filtered_df['data_gb'] >= 999) | (filtered_df['plan_name'].str.contains('무제한', na=False))
            ]
        else:
            filtered_df = filtered_df[filtered_df['data_gb'] >= params['data_gb']]
            
    # 혜택 키워드 필터링
    if "benefit_keyword" in params:
        keyword = params['benefit_keyword'].lower()
        filtered_df = filtered_df[
            filtered_df['benefits'].astype(str).str.lower().str.contains(keyword, na=False)
        ]
        
    # 카테고리 (5G/LTE) 필터링
    if "category" in params:
        category = params['category'].upper()
        filtered_df = filtered_df[
            filtered_df['category'].astype(str).str.upper().str.contains(category, na=False)
        ]

    # 할인 제외 필터링
    if params.get("exclude_discount"):
        filtered_df = filtered_df[
            ~filtered_df['plan_name'].astype(str).str.contains('할인', na=False)
        ]
            
    return filtered_df.sort_values(by='monthly_fee').reset_index(drop=True)


def generate_plan_response(plans_df: pd.DataFrame) -> str:
    """검색된 요금제 정보를 바탕으로 응답 생성"""
    
    if plans_df.empty:
        return "죄송합니다. 고객님의 조건에 맞는 요금제를 찾을 수 없습니다. 조건을 좀 더 완화하여 다시 말씀해주시겠어요?"
        
    response_parts = ["고객님께 추천하는 요금제는 다음과 같습니다:"]
    
    for _, plan in plans_df.head(3).iterrows(): # 상위 3개만 추천
        response_parts.append(f"- **{plan['plan_name']}**")
        response_parts.append(f"  월 {int(plan['monthly_fee']):,}원")
        
        data_info = f"{int(plan['data_gb'])}GB" if plan['data_gb'] < 999 else "데이터 무제한"
        voice_info = f"{int(plan['voice_min'])}분" if plan['voice_min'] > 0 else "음성 무제한"
        sms_info = f"{int(plan['sms_count'])}건" if plan['sms_count'] > 0 else "문자 무제한"
        
        response_parts.append(f"  ({data_info} / {voice_info} / {sms_info})")
        
        if pd.notna(plan['benefits']) and plan['benefits'].strip():
            response_parts.append(f"  혜택: {plan['benefits']}")
        link = plan.get('link', None)
        if link is not None and pd.notna(link) and str(link).strip():
            response_parts.append(f"  [자세히 보기]({link})")
            
    if len(plans_df) > 3:
        response_parts.append(f"\n이 외에도 {len(plans_df) - 3}개의 요금제가 더 있습니다.")
        
    return "\n".join(response_parts)

# ============================================
# FastAPI 라우트
# ============================================
@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        intent_result = extract_intent(request.message)
        
        is_plan_query = intent_result.get("is_plan_query", False)
        intent_type = intent_result.get("intent_type", "chit_chat")
        params = intent_result.get("params", {})
        
        messages = []
        
        if intent_type == "greeting":
            messages.append({"role": "bot", "content": "안녕하세요! 어떤 요금제를 찾으시나요?"})
        elif intent_type == "chit_chat":
            messages.append({"role": "bot", "content": "요금제 관련 질문을 해주시면 더 정확한 답변을 드릴 수 있습니다."})
        elif is_plan_query and intent_type == "plan_search":
            plans = search_plans(params)
            response_content = generate_plan_response(plans)
            messages.append({"role": "bot", "content": response_content})
        else:
            messages.append({"role": "bot", "content": "죄송합니다. 요청을 이해하지 못했습니다. 다시 말씀해주시겠어요?"})
            
        return ChatResponse(success=True, messages=messages)
        
    except Exception as e:
        print(f"API 오류: {e}")
        return ChatResponse(success=False, messages=[], error=str(e))

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _resolve_port():
    import socket
    env_port = os.environ.get("APP_PORT") or os.environ.get("GRADIO_SERVER_PORT") or os.environ.get("PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    for port in range(7861, 7899):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return 7861

if __name__ == "__main__":
    import uvicorn
    port = _resolve_port()
    print(f"[PayLink] Starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
