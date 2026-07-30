-- Roll back Gamma-6 route incident writable approval API artifacts.

DROP TABLE IF EXISTS qmeta.source_route_incident_approval_command_item CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_incident_approval_signature CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_incident_approval_command CASCADE;

