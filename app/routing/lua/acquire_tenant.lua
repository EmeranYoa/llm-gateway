-- Decide, atomically, whether a tenant may send one more request, and count it.
--
-- Run once per request, before routing. Two quotas are checked:
--
-- * requests per minute: the request stays counted whatever happens next, even
--   when every provider then fails, so a tenant whose requests all fail cannot
--   hammer the gateway;
-- * the daily token budget: the token estimate of the request is reserved now,
--   then corrected or released after the request (see record_tenant_outcome.lua).
--
-- KEYS[1]  RPM window of the tenant: sorted set of requests "<id>", scored by time in milliseconds
-- KEYS[2]  token budget counter of the tenant for the current UTC day
-- ARGV[1]  request id, unique per request
-- ARGV[2]  RPM limit of the tenant (0 means no limit)
-- ARGV[3]  estimated tokens of the request
-- ARGV[4]  daily token budget of the tenant (0 means no limit)
-- ARGV[5]  next midnight UTC, as a Unix time in milliseconds: when the budget resets
--
-- Returns {"ok"} when the request is counted and its tokens reserved, or a refusal:
-- {"rpm", wait_ms} or {"tokens_per_day", wait_ms, remaining_tokens}. The request may
-- be sent again in wait_ms milliseconds. Nothing is written unless both checks pass.

local WINDOW_MS = 60000

local request_id = ARGV[1]
local rpm_limit = tonumber(ARGV[2])
local tokens = tonumber(ARGV[3])
local budget = tonumber(ARGV[4])
local next_midnight_ms = tonumber(ARGV[5])

if rpm_limit == 0 and budget == 0 then
  return {"ok"}
end

-- Redis time, so every gateway instance uses the same clock.
local time = redis.call("TIME")
local now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

-- 1. Requests per minute.
if rpm_limit > 0 then
  -- Forget requests older than the window.
  redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", now_ms - WINDOW_MS)
  if redis.call("ZCARD", KEYS[1]) >= rpm_limit then
    -- Wait until the oldest request leaves the window.
    local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
    return {"rpm", math.max(tonumber(oldest[2]) + WINDOW_MS - now_ms, 1)}
  end
end

-- 2. Daily token budget.
if budget > 0 then
  local used_today = tonumber(redis.call("GET", KEYS[2]) or "0")
  if used_today + tokens > budget then
    -- Wait until the budget resets at midnight UTC.
    return {"tokens_per_day", math.max(next_midnight_ms - now_ms, 1), math.max(budget - used_today, 0)}
  end
end

-- 3. Both checks passed: count the request and reserve its tokens.
if rpm_limit > 0 then
  redis.call("ZADD", KEYS[1], now_ms, request_id)
  redis.call("PEXPIRE", KEYS[1], WINDOW_MS)
end
if budget > 0 then
  redis.call("INCRBY", KEYS[2], tokens)
  redis.call("PEXPIREAT", KEYS[2], next_midnight_ms)
end
return {"ok"}
