#!lua flags=no-writes
-- Read the state of a target that acquire_target.lua checks, for the admin API.
--
-- The "no-writes" flag above makes Redis refuse any write: reading the state of a
-- target can never change it. One script, so every value is read at the same moment.
--
-- KEYS[1]  cooldown key of the target
-- KEYS[2]  RPM window: sorted set of reservations "<id>", scored by time in milliseconds
-- KEYS[3]  TPM window: sorted set of reservations "<id>:<tokens>", scored the same way
-- KEYS[4]  RPD counter of the current quota day
-- KEYS[5]  breaker "open" key: exists (with a TTL) while the breaker is open
-- KEYS[6]  breaker "half-open" marker: exists once the breaker has opened, until a trial succeeds
-- KEYS[7]  breaker trial slot: exists while the single half-open trial call is running
--
-- Returns {now_ms, cooldown_ms, open_ms, half_open, trial_ms, rpm_used, tpm_used, rpd_used}:
-- the Redis time, the time left of the cooldown, of the open breaker and of the trial
-- slot (0 when there is none), 1 when the half-open marker exists, the requests and
-- tokens reserved in the last 60 s, and the requests counted today.

local WINDOW_MS = 60000

local function tokens_of(member)
  return tonumber(string.match(member, ":(%d+)$"))
end

-- Time left of a key with a TTL, or 0 when the key does not exist (PTTL returns -2).
local function time_left_ms(key)
  return math.max(redis.call("PTTL", key), 0)
end

-- Redis time, the same clock as acquire_target.lua.
local time = redis.call("TIME")
local now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

-- acquire_target.lua removes reservations scored up to `now - 60 s` included before
-- it counts, so the window holds the ones scored strictly after it.
local window_start = "(" .. (now_ms - WINDOW_MS)

local rpm_used = redis.call("ZCOUNT", KEYS[2], window_start, "+inf")

local tpm_used = 0
for _, member in ipairs(redis.call("ZRANGEBYSCORE", KEYS[3], window_start, "+inf")) do
  tpm_used = tpm_used + tokens_of(member)
end

local rpd_used = tonumber(redis.call("GET", KEYS[4]) or "0")

return {
  now_ms,
  time_left_ms(KEYS[1]),
  time_left_ms(KEYS[5]),
  redis.call("EXISTS", KEYS[6]),
  time_left_ms(KEYS[7]),
  rpm_used,
  tpm_used,
  rpd_used,
}
