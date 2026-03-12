import {
  pgTable,
  text,
  uuid,
  timestamp,
  real,
  jsonb,
} from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";

export const signalsTable = pgTable("signals", {
  id: uuid("id").defaultRandom().primaryKey(),
  agentId: text("agent_id").notNull(),
  timestamp: timestamp("timestamp", { withTimezone: true }).notNull().defaultNow(),
  underlying: text("underlying").notNull(),
  direction: text("direction").notNull(),
  confidence: real("confidence").notNull(),
  timeframe: text("timeframe").notNull(),
  reasoning: text("reasoning").notNull(),
  supportingData: jsonb("supporting_data"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const insertSignalSchema = createInsertSchema(signalsTable).omit({
  id: true,
  createdAt: true,
});
export type InsertSignal = z.infer<typeof insertSignalSchema>;
export type Signal = typeof signalsTable.$inferSelect;
