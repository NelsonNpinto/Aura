import "server-only";
import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { buildAuthOptions } from "./auth-options";
import { pool } from "./db";

const options = buildAuthOptions(pool);

export const auth = betterAuth({ ...options, plugins: [...(options.plugins ?? []), nextCookies()] });
