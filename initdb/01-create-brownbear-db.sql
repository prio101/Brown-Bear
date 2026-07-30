-- Roadmap decision D3: Brown Bear gets its own database inside the existing
-- postgres container. VectorAdmin owns `vdbms` and runs its own migrations
-- there; adding our tables to it risks silent loss on a VectorAdmin upgrade.
--
-- NOTE: files in /docker-entrypoint-initdb.d only run when the data directory
-- is empty. On an already-initialised volume, create the database manually:
--   docker exec postgres psql -U vectoradmin -d vdbms -c 'CREATE DATABASE brownbear'
SELECT 'CREATE DATABASE brownbear'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'brownbear')\gexec
