// vitest 全局 setup：React 18 的 act() 需要显式声明这是测试环境（否则每次
// act 都打 "current testing environment is not configured to support act" 警告）。
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
