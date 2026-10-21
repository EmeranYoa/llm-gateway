-- Decide, atomically, whether a target can be called now (see ADR 0001).
--
-- KEYS[1]  cooldown key of the target
--
-- Returns {"ok"} when the target can be called,
-- or {reason, wait_ms} when it must be skipped for wait_ms milliseconds.

local cooldown_ms = redis.call("PTTL", KEYS[1])
if cooldown_ms > 0 then
  return {"cooldown", cooldown_ms}
end

return {"ok"}
