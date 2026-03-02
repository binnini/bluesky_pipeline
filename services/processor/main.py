# confluent-kafka Consumer 루프
# - Redpanda(bluesky-raw topic) 구독
# - 메시지를 aggregator.py로 전달
# - 1분 윈도우 완료 시 TimescaleDB INSERT 트리거
