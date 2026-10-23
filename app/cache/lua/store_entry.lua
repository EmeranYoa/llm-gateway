-- Store one answer in the response cache, atomically.
--
-- Two concurrent writes must never both pass the checks, so the checks and the
-- write happen in one script:
-- * an entry with the same exact key already exists: keep it (the first answer
--   wins), unless the client asked to replace it (bypass);
-- * the tenant already has its maximum number of entries: write nothing.
--
-- Each tenant has a sorted set of its entry keys, scored by their expiry time,
-- to count its live entries: Redis has no event when a key expires, so expired
-- members are removed here before counting.
--
-- KEYS[1]  the entry key (a hash)
-- KEYS[2]  the sorted set of the tenant's entries
-- ARGV[1]  TTL of the entry, in milliseconds
-- ARGV[2]  maximum number of entries of the tenant (0: no limit)
-- ARGV[3]  "1" to replace an existing entry, "0" to keep it
-- ARGV[4…] the fields and values of the entry
--
-- Returns "ok", "exists" or "full".

local time = redis.call("TIME")
local now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
local ttl_ms = tonumber(ARGV[1])
local max_entries = tonumber(ARGV[2])

redis.call("ZREMRANGEBYSCORE", KEYS[2], "-inf", now_ms)
local exists = redis.call("EXISTS", KEYS[1]) == 1
if exists and ARGV[3] ~= "1" then
  return "exists"
end
if not exists and max_entries > 0 and redis.call("ZCARD", KEYS[2]) >= max_entries then
  return "full"
end

-- A replaced entry starts empty: no field of the old answer (its vector) is kept.
redis.call("DEL", KEYS[1])
redis.call("HSET", KEYS[1], unpack(ARGV, 4))
redis.call("PEXPIRE", KEYS[1], ttl_ms)
redis.call("ZADD", KEYS[2], now_ms + ttl_ms, KEYS[1])
-- The set lives as long as its longest-lived entry.
local last = redis.call("ZRANGE", KEYS[2], -1, -1, "WITHSCORES")
redis.call("PEXPIREAT", KEYS[2], last[2])
return "ok"
