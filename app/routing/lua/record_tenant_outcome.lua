-- Update, atomically, the daily token budget of a tenant once a request is over.
--
-- acquire_tenant.lua reserved the token estimate of the request. This script
-- replaces it with the real usage, or gives it back.
--
-- KEYS[1]  token budget counter of the UTC day the tokens were reserved in
-- ARGV[1]  tokens reserved for the request
-- ARGV[2]  what to do with them: "correct" (replace with the real usage) or "release"
-- ARGV[3]  tokens really used, for "correct"
--
-- Returns the tokens now used in the day, or -1 when the counter no longer exists.

-- The counter expires at midnight UTC. If the request ran past midnight, the
-- budget has already been reset: there is nothing left to correct. Checking
-- first also avoids creating a counter that would never expire.
if redis.call("EXISTS", KEYS[1]) == 0 then
  return -1
end

local reserved = tonumber(ARGV[1])
local action = ARGV[2]
local used = tonumber(ARGV[3])

-- INCRBY keeps the expiry set by acquire_tenant.lua.
if action == "release" then
  return redis.call("INCRBY", KEYS[1], -reserved)
end
return redis.call("INCRBY", KEYS[1], used - reserved)
