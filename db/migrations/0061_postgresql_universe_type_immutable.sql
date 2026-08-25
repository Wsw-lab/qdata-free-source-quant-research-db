-- universe_type selects the membership semantics used by PIT readers.  An
-- in-place change would reinterpret already-published history, so upgrades
-- install the same immutable-type guard used by the canonical fresh schema.

CREATE OR REPLACE FUNCTION qmeta.reject_universe_type_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.universe_type IS DISTINCT FROM OLD.universe_type THEN
        RAISE EXCEPTION
            'universe_type is immutable for universe_id %; create a new universe instead',
            OLD.universe_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_universe_type_immutable
    ON qmeta.universe_definition;

CREATE TRIGGER trg_universe_type_immutable
    BEFORE UPDATE OF universe_type ON qmeta.universe_definition
    FOR EACH ROW
    EXECUTE FUNCTION qmeta.reject_universe_type_change();
