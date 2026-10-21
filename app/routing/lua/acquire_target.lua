-- Decide, atomically, whether a target can be called now, and reserve its quota (see ADR 0001).
--
-- KEYS[1]  cooldown key of the target
-- KEYS[2]  RPM window: sorted set of reservations "<id>", scored by time in milliseconds
-- KEYS[3]  TPM window: sorted set of reservations "<id>:<tokens>", scored the same way
-- KEYS[4]  RPD counter of the current quota day
-- KEYS[5]  breaker "open" key: exists (with a TTL) while the breaker is open
-- KEYS[6]  breaker "half-open" marker: exists once the breaker has opened, until a trial succeeds
-- KEYS[7]  breaker trial slot: exists while the single half-open trial call is running
-- ARGV[1]  reservation id, unique per call
-- ARGV[2]  estimated tokens of the call
-- ARGV[3]  RPM limit (0 means no limit)
-- ARGV[4]  TPM limit (0 means no limit)
-- ARGV[5]  RPD limit (0 means no limit)
-- ARGV[6]  next daily reset of the provider, as a Unix time in milliseconds
-- ARGV[7]  attempt timeout in milliseconds: how long a trial slot is held at most
--
-- Returns {"ok", is_trial} when the target can be called (its quota is then reserved,
-- and is_trial is 1 when this call is the half-open trial), or {reason, wait_ms}
-- when it must be skipped for wait_ms milliseconds. Nothing is written unless every
-- check passes.

local WINDOW_MS = 60000

local function tokens_of(member)
  return tonumber(string.match(member, ":(%d+)$"))
end

-- 1. Cooldown.
local cooldown_ms = redis.call("PTTL", KEYS[1])
if cooldown_ms > 0 then
  return {"cooldown", cooldown_ms}
end

-- 2. Circuit breaker.
local open_ms = redis.call("PTTL", KEYS[5])
if open_ms > 0 then
  return {"breaker", open_ms}
end
local is_trial = false
if redis.call("EXISTS", KEYS[6]) == 1 then
  -- Half-open: only one trial call at a time.
  local trial_ms = redis.call("PTTL", KEYS[7])
  if trial_ms > 0 then
    return {"breaker", trial_ms}
  end
  is_trial = true
end

-- 3. Quotas. Redis time, so every gateway instance uses the same clock.
local time = redis.call("TIME")
local now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

local reservation_id = ARGV[1]
local tokens = tonumber(ARGV[2])
local rpm_limit = tonumber(ARGV[3])
local tpm_limit = tonumber(ARGV[4])
local rpd_limit = tonumber(ARGV[5])
local next_reset_ms = tonumber(ARGV[6])
local trial_slot_ms = tonumber(ARGV[7])

if rpm_limit > 0 then
  -- Forget reservations older than the window.
  redis.call("ZREMRANGEBYSCORE", KEYS[2], "-inf", now_ms - WINDOW_MS)
  if redis.call("ZCARD", KEYS[2]) >= rpm_limit then
    -- Wait until the oldest reservation leaves the window.
    local oldest = redis.call("ZRANGE", KEYS[2], 0, 0, "WITHSCORES")
    return {"rpm", math.max(tonumber(oldest[2]) + WINDOW_MS - now_ms, 1)}
  end
end

if tpm_limit > 0 then
  redis.call("ZREMRANGEBYSCORE", KEYS[3], "-inf", now_ms - WINDOW_MS)
  local entries = redis.call("ZRANGE", KEYS[3], 0, -1, "WITHSCORES")
  local used = 0
  for i = 1, #entries, 2 do
    used = used + tokens_of(entries[i])
  end
  if used + tokens > tpm_limit then
    -- Wait until enough of the oldest reservations leave the window.
    local wait_ms = WINDOW_MS
    local freed = 0
    for i = 1, #entries, 2 do
      freed = freed + tokens_of(entries[i])
      if used - freed + tokens <= tpm_limit then
        wait_ms = tonumber(entries[i + 1]) + WINDOW_MS - now_ms
        break
      end
    end
    return {"tpm", math.max(wait_ms, 1)}
  end
end

if rpd_limit > 0 then
  local used_today = tonumber(redis.call("GET", KEYS[4]) or "0")
  if used_today >= rpd_limit then
    -- Wait until the provider resets its daily quota.
    return {"rpd", math.max(next_reset_ms - now_ms, 1)}
  end
end

-- 4. Every check passed: reserve.
if rpm_limit > 0 then
  redis.call("ZADD", KEYS[2], now_ms, reservation_id)
  redis.call("PEXPIRE", KEYS[2], WINDOW_MS)
end
if tpm_limit > 0 then
  redis.call("ZADD", KEYS[3], now_ms, reservation_id .. ":" .. tokens)
  redis.call("PEXPIRE", KEYS[3], WINDOW_MS)
end
if rpd_limit > 0 then
  redis.call("INCR", KEYS[4])
  redis.call("PEXPIREAT", KEYS[4], next_reset_ms)
end
if is_trial then
  -- The slot frees itself if this gateway instance dies during the trial call.
  redis.call("SET", KEYS[7], reservation_id, "PX", trial_slot_ms)
end

return {"ok", is_trial and 1 or 0}
