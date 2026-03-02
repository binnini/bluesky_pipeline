# 1분 버킷 집계, 키워드 전처리, TimescaleDB INSERT
#
# 키워드 전처리 순서:
#   1. 소문자 변환
#   2. 특수문자 제거
#   3. NLTK English stopwords 제거
#   4. 길이 필터 (2자 이상, 50자 이하)
#   5. 빈도 집계 → 3회 이상만 keyword_trends에 저장
