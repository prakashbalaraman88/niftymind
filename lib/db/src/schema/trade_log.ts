import {
  pgTable,
  text,
  uuid,
  timestamp,
  real,
  integer,
  jsonb,
} from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";
import { tradesTable } from "./trades";

export const tradeLogTable = pgTable("trade_log", {
  id: uuid("id").defaultRandom().primaryKey(),
  tradeId: text("trade_id")
    .notNull()
    .references(() => tradesTable.tradeId),
  event: text("event").notNull(),
  status: text("status").notNull(),
  price: real("price"),
  quantity: integer("quantity"),
  pnl: real("pnl"),
  agentVotes: jsonb("agent_votes"),
  consensusScore: real("consensus_score"),
  riskApproval: text("risk_approval"),
  riskReasoning: text("risk_reasoning"),
  details: jsonb("details"),
  timestamp: timestamp("timestamp", { withTimezone: true }).notNull().defaultNow(),
});

export const insertTradeLogSchema = createInsertSchema(tradeLogTable).omit({
  id: true,
  timestamp: true,
});
export type InsertTradeLog = z.infer<typeof insertTradeLogSchema>;
export type TradeLog = typeof tradeLogTable.$inferSelect;
