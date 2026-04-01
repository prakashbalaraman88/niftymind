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

export const tradesTable = pgTable("trades", {
  id: uuid("id").defaultRandom().primaryKey(),
  tradeId: text("trade_id").notNull().unique(),
  symbol: text("symbol").notNull(),
  underlying: text("underlying").notNull(),
  direction: text("direction").notNull(),
  entryPrice: real("entry_price"),
  slPrice: real("sl_price"),
  targetPrice: real("target_price"),
  exitPrice: real("exit_price"),
  quantity: integer("quantity").notNull(),
  status: text("status").notNull().default("PENDING"),
  pnl: real("pnl").default(0),
  exitReason: text("exit_reason"),
  consensusScore: real("consensus_score"),
  tradeType: text("trade_type").notNull(),
  entryTime: timestamp("entry_time", { withTimezone: true }),
  exitTime: timestamp("exit_time", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const insertTradeSchema = createInsertSchema(tradesTable).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});
export type InsertTrade = z.infer<typeof insertTradeSchema>;
export type Trade = typeof tradesTable.$inferSelect;
