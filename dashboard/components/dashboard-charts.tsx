"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { DECISION_LABELS } from "@/lib/types"
import type { JobPosting } from "@/lib/types"
import {
  decisionDistribution,
  pipelineFunnel,
  scoreHistogram,
  sourceDistribution,
  weeklyTrend,
} from "@/lib/stats"

const DECISION_COLORS: Record<string, string> = {
  APPLY_NOW: "var(--success)",
  APPLY_WITH_TAILORED_CV: "var(--info)",
  MAYBE: "var(--warning)",
  SKIP: "var(--neutral-muted-foreground)",
  AVOID: "var(--destructive)",
}

function ChartCard({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <Card className="gap-3">
      <CardHeader className="gap-0.5 pb-0">
        <CardTitle className="text-sm">{title}</CardTitle>
        <CardDescription className="text-xs">{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function DashboardCharts({ jobs }: { jobs: JobPosting[] }) {
  const decisions = decisionDistribution(jobs).map((d) => ({
    ...d,
    label: DECISION_LABELS[d.decision],
    fill: DECISION_COLORS[d.decision],
  }))
  const sources = sourceDistribution(jobs)
  const trend = weeklyTrend(jobs)
  const funnel = pipelineFunnel(jobs)
  const histogram = scoreHistogram(jobs)

  const barConfig = {
    count: { label: "Jobs", color: "var(--chart-1)" },
  } satisfies ChartConfig

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <ChartCard
        title="Decision distribution"
        description="How opportunities are ranked"
      >
        <ChartContainer config={barConfig} className="h-48 w-full">
          <BarChart accessibilityLayer data={decisions} margin={{ left: -20 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              fontSize={11}
              interval={0}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              fontSize={11}
              allowDecimals={false}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" radius={6}>
              {decisions.map((d) => (
                <Cell key={d.decision} fill={d.fill} />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Opportunities by source"
        description="Where jobs are coming from"
      >
        <ChartContainer config={barConfig} className="h-48 w-full">
          <BarChart
            accessibilityLayer
            data={sources}
            layout="vertical"
            margin={{ left: 8 }}
          >
            <CartesianGrid horizontal={false} strokeDasharray="3 3" />
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="source"
              tickLine={false}
              axisLine={false}
              fontSize={11}
              width={72}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar
              dataKey="count"
              radius={6}
              fill="var(--chart-1)"
            />
          </BarChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Weekly trend"
        description="New jobs found per day"
      >
        <ChartContainer config={barConfig} className="h-48 w-full">
          <LineChart accessibilityLayer data={trend} margin={{ left: -20 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              fontSize={11}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              fontSize={11}
              allowDecimals={false}
            />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line
              dataKey="count"
              type="monotone"
              stroke="var(--chart-1)"
              strokeWidth={2}
              dot={{ r: 3, fill: "var(--chart-1)" }}
            />
          </LineChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Pipeline funnel"
        description="Progress from new to applied"
      >
        <ChartContainer config={barConfig} className="h-48 w-full">
          <BarChart
            accessibilityLayer
            data={funnel}
            layout="vertical"
            margin={{ left: 8 }}
          >
            <CartesianGrid horizontal={false} strokeDasharray="3 3" />
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="stage"
              tickLine={false}
              axisLine={false}
              fontSize={11}
              width={72}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" radius={6} fill="var(--chart-2)" />
          </BarChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Score distribution"
        description="Spread of ranking scores"
      >
        <ChartContainer config={barConfig} className="h-48 w-full">
          <BarChart accessibilityLayer data={histogram} margin={{ left: -20 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="range"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              fontSize={11}
              interval={0}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              fontSize={11}
              allowDecimals={false}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" radius={6} fill="var(--chart-3)" />
          </BarChart>
        </ChartContainer>
      </ChartCard>
    </div>
  )
}
