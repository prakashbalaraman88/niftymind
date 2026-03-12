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
import { tradesTable } from "./trades";

export const agentVotesTable = pgTable("agent_votes", {
  id: uuid("id").defaultRandom().primaryKey(),
  tradeId: text("trade_id")
    .notNull()
    .references(() => tradesTable.tradeId),
  agentId: text("agent_id").notNull(),
  direction: text("direction").notNull(),
  confidence: real("confidence").notNull(),
  weight: real("weight").notNull(),
  weightedScore: real("weighted_score").notNull(),
  reasoning: text("reasoning").notNull(),
  supportingData: jsonb("supporting_data"),
  votedAt: timestamp("voted_at", { withTimezone: true }).notNull().defaultNow(),
});

export const insertAgentVoteSchema = createInsertSchema(agentVotesTable).omit({
  id: true,
  votedAt: true,
});
export type InsertAgentVote = z.infer<typeof insertAgentVoteSchema>;
export type AgentVote = typeof agentVotesTable.$inferSelect;
