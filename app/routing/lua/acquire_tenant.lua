-- Decide, atomically, whether a tenant may send one more request, and count it.
--
-- Run once per request, before routing. The request stays counted whatever
-- happens next, even when every provider then fails: a tenant whose requests all
-- fail must not be able to hammer the gateway.
--
-- KEYS[1]  RPM window of the tenant: sorted set of requests "<id>", scored by time in milliseconds
-- ARGV[1]  request id, unique per request
-- ARGV[2]  RPM limit of the tenant (0 means no limit)
--
-- Returns {"ok"} when the request is counted, or {"rpm", wait_ms} when the limit is
-- reached: the request may be sent again in wait_ms milliseconds. Nothing is written
-- for a refused request.

local WINDOW_MS = 60000

local request_id = ARGV[1]
local rpm_limit = tonumber(ARGV[2])

if rpm_limit == 0 then
  return {"ok"}
end

-- Redis time, so every gateway instance uses the same clock.
local time = redis.call("TIME")
local now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

-- Forget requests older than the window.
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", now_ms - WINDOW_MS)
if redis.call("ZCARD", KEYS[1]) >= rpm_limit then
  -- Wait until the oldest request leaves the window.
  local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
  return {"rpm", math.max(tonumber(oldest[2]) + WINDOW_MS - now_ms, 1)}
end

redis.call("ZADD", KEYS[1], now_ms, request_id)
redis.call("PEXPIRE", KEYS[1], WINDOW_MS)
return {"ok"}
