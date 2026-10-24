-- Update, atomically, the state of a target after a call.
--
-- KEYS[1]  cooldown key of the target
-- KEYS[2]  counter of consecutive 429 responses of the target
-- KEYS[3]  TPM window of the target (see acquire_target.lua)
-- KEYS[4]  breaker failure window: sorted set of failed calls, scored by time in milliseconds
-- KEYS[5]  breaker "open" key
-- KEYS[6]  breaker "half-open" marker
-- KEYS[7]  breaker trial slot
-- KEYS[8]  TPM counter: total tokens of the TPM window (see acquire_target.lua)
-- ARGV[1]  cooldown outcome: "success", "rate_limited", "misconfigured" or "none"
-- ARGV[2]  retry delay in milliseconds given by the provider, or -1 when unknown
-- ARGV[3]  first progressive cooldown, in milliseconds
-- ARGV[4]  maximum progressive cooldown, in milliseconds
-- ARGV[5]  cooldown after a misconfiguration error, in milliseconds
-- ARGV[6]  reservation id of the call
-- ARGV[7]  tokens reserved for the call
-- ARGV[8]  what to do with the reserved tokens: "correct", "release" or "keep"
-- ARGV[9]  tokens really used, for "correct" (-1 when the provider did not say)
-- ARGV[10] breaker result: "success", "failure" or "neutral"
-- ARGV[11] 1 when the call was the half-open trial, else 0
-- ARGV[12] breaker: failures within the window that open it
-- ARGV[13] breaker: failure window, in milliseconds
-- ARGV[14] breaker: how long it stays open, in milliseconds
--
-- Returns the cooldown now applied to the target, in milliseconds (0 for none).

-- 1. Token accounting. The request itself always stays in the RPM window and
-- the RPD counter: the provider may have counted it even when the call failed.
local reservation_id = ARGV[6]
local reserved_tokens = tonumber(ARGV[7])
local reserved_member = reservation_id .. ":" .. ARGV[7]
local token_action = ARGV[8]
local used_tokens = tonumber(ARGV[9])

-- Keep the TPM counter equal to its window. INCRBY keeps the TTL of the counter, the
-- same as the window's. Without a counter (upgrade from v0.5.1), the next call of
-- acquire_target.lua rebuilds it from the window.
local function add_to_counter(delta)
  if delta ~= 0 and redis.call("EXISTS", KEYS[8]) == 1 then
    redis.call("INCRBY", KEYS[8], delta)
  end
end

-- Only a reservation still in the window changes it: one that already left it was
-- subtracted from the counter then.
if token_action == "release" then
  if redis.call("ZREM", KEYS[3], reserved_member) == 1 then
    add_to_counter(-reserved_tokens)
  end
elseif token_action == "correct" and used_tokens >= 0 then
  -- Keep the reservation time, replace the estimate with the real usage.
  local reserved_at = redis.call("ZSCORE", KEYS[3], reserved_member)
  if reserved_at then
    redis.call("ZREM", KEYS[3], reserved_member)
    redis.call("ZADD", KEYS[3], reserved_at, reservation_id .. ":" .. used_tokens)
    add_to_counter(used_tokens - reserved_tokens)
  end
end

-- 2. Circuit breaker.
local breaker_result = ARGV[10]
local is_trial = ARGV[11] == "1"
local failure_threshold = tonumber(ARGV[12])
local failure_window_ms = tonumber(ARGV[13])
local open_ms = tonumber(ARGV[14])

local function open_breaker()
  redis.call("SET", KEYS[5], 1, "PX", open_ms)
  redis.call("SET", KEYS[6], 1)
  redis.call("DEL", KEYS[4])
end

if is_trial then
  redis.call("DEL", KEYS[7])
  if breaker_result == "success" then
    -- Half-open -> closed.
    redis.call("DEL", KEYS[6])
  elseif breaker_result == "failure" then
    -- Half-open -> open again.
    open_breaker()
  end
  -- Neutral: the slot is free again, the breaker stays half-open.
elseif breaker_result == "failure" then
  local time = redis.call("TIME")
  local now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
  redis.call("ZREMRANGEBYSCORE", KEYS[4], "-inf", now_ms - failure_window_ms)
  redis.call("ZADD", KEYS[4], now_ms, reservation_id)
  redis.call("PEXPIRE", KEYS[4], failure_window_ms)
  if redis.call("ZCARD", KEYS[4]) >= failure_threshold then
    -- Closed -> open.
    open_breaker()
  end
end

-- 3. Cooldown.
local outcome = ARGV[1]

if outcome == "success" then
  redis.call("DEL", KEYS[2])
  return 0
end

if outcome == "rate_limited" then
  local retry_ms = tonumber(ARGV[2])
  local initial_ms = tonumber(ARGV[3])
  local max_ms = tonumber(ARGV[4])

  local streak = redis.call("INCR", KEYS[2])
  -- Keep the streak long enough to survive the longest cooldown.
  redis.call("PEXPIRE", KEYS[2], max_ms * 2)

  local cooldown_ms = retry_ms
  if retry_ms < 0 then
    -- No delay from the provider: 1x, 2x, 4x... the first cooldown, capped.
    cooldown_ms = math.min(initial_ms * 2 ^ (streak - 1), max_ms)
  end
  cooldown_ms = math.max(math.floor(cooldown_ms), 1)
  redis.call("SET", KEYS[1], 1, "PX", cooldown_ms)
  return cooldown_ms
end

if outcome == "misconfigured" then
  local cooldown_ms = tonumber(ARGV[5])
  redis.call("SET", KEYS[1], 1, "PX", cooldown_ms)
  return cooldown_ms
end

return 0
