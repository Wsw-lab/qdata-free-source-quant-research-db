-- 回滚 Mu 后台调度器、锁和心跳对象

DROP TABLE IF EXISTS qmeta.worker_schedule_tick CASCADE;
DROP TABLE IF EXISTS qmeta.worker_heartbeat CASCADE;
DROP TABLE IF EXISTS qmeta.worker_lock CASCADE;
DROP TABLE IF EXISTS qmeta.worker_schedule CASCADE;
