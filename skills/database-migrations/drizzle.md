# Drizzle (TypeScript/Node.js)

Install it in the project if it is not already a dependency — `npm install drizzle-orm` and
`npm install --save-dev drizzle-kit` — and run the pinned version through `npx`
(`npx drizzle-kit --version`).

## Workflow

```bash
# Generate migration from schema changes
npx drizzle-kit generate

# Apply migrations
npx drizzle-kit migrate

# Push schema directly (dev only, no migration file)
npx drizzle-kit push
```

## Schema Example

```typescript
import { pgTable, text, timestamp, integer, boolean, uniqueIndex } from "drizzle-orm/pg-core";

export const member = pgTable("member", {
  // Bounded entity table -> integer identity, not uuid().defaultRandom(): that is UUIDv4,
  // whose insert positions scatter. UUIDv7 (or an integer PK + a public UID column) is the
  // choice when you actually need distributed or externally visible IDs.
  memberId: integer("member_id").primaryKey().generatedAlwaysAsIdentity(),
  email: text("email").notNull(),
  name: text("name"),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => ({
  // Named, per rdbms-naming — a bare .unique() lets Drizzle generate the constraint name
  uqMemberEmail: uniqueIndex("uq_member_email").on(table.email),
}));
```
