# Firehose WebSocket consumer
# - atproto SDK로 BlueSky Firehose 연결
# - 수신 이벤트를 Redpanda(bluesky-raw topic)로 Produce
# - reconnect.py의 Exponential Backoff 사용
