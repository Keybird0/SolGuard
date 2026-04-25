import type { NextFunction, Request, Response } from 'express';
import { ZodError } from 'zod';
import { logger } from '../logger';
import type { ApiError } from '../types';

export function notFoundHandler(_req: Request, res: Response): void {
  const err: ApiError = { code: 'NOT_FOUND', message: 'Resource not found' };
  res.status(404).json(err);
}

export function errorHandler(
  err: unknown,
  req: Request,
  res: Response,
  _next: NextFunction,
): void {
  if (err instanceof ZodError) {
    logger.warn(
      { issues: err.errors, path: req.path, method: req.method },
      'ZodError validation failed',
    );
    const apiErr: ApiError = {
      code: 'VALIDATION_ERROR',
      message: 'Invalid request payload',
      details: err.errors,
    };
    res.status(400).json(apiErr);
    return;
  }

  const isKnown = err instanceof Error;
  logger.error(
    {
      err: isKnown ? { message: err.message, stack: err.stack } : err,
      path: req.path,
      method: req.method,
    },
    'Unhandled error',
  );

  const apiErr: ApiError = {
    code: 'INTERNAL_ERROR',
    message: 'Something went wrong. Please try again.',
  };
  res.status(500).json(apiErr);
}
