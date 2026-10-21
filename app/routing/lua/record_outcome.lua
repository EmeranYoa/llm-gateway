-- Update, atomically, the state of a target after a call.
--
-- KEYS[1]  cooldown key of the target
-- KEYS[2]  counter of consecutive 429 responses of the target
-- ARGV[1]  outcome: "success", "rate_limited" or "misconfigured"
-- ARGV[2]  retry delay in milliseconds given by the provider, or -1 when unknown
-- ARGV[3]  first progressive cooldown, in milliseconds
-- ARGV[4]  maximum progressive cooldown, in milliseconds
-- ARGV[5]  cooldown after a misconfiguration error, in milliseconds
--
-- Returns the cooldown now applied to the target, in milliseconds (0 for none).

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
