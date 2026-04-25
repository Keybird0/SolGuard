// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { spawnSync } from 'node:child_process';
import { Router } from 'express';
import {
  config,
  hasAnyLlmKey,
  isEmailConfigured,
  isLarkConfigured,
  isPaymentConfigured,
} from '../config';

const router = Router();

function checkOhCli(): boolean {
  try {
    const result = spawnSync(config.ohCliPath, ['--version'], {
      stdio: 'ignore',
      timeout: 3000,
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

router.get('/healthz', (_req, res) => {
  res.json({
    status: 'ok',
    version: config.appVersion,
    environment: config.nodeEnv,
    checks: {
      ohCli: checkOhCli(),
      llmKey: hasAnyLlmKey(),
      solanaCluster: config.solanaCluster,
      paymentConfigured: isPaymentConfigured(),
      emailConfigured: isEmailConfigured(),
      larkConfigured: isLarkConfigured(),
      freeAudit: config.freeAudit,
      auditPriceSol: config.auditPriceSol,
    },
    timestamp: new Date().toISOString(),
  });
});

export default router;
