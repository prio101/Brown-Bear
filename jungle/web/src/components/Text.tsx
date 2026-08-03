import type { CSSProperties, ElementType, ReactNode } from "react";

/**
 * Typed access to the type scale (BB-102 §102.3).
 *
 * The point is not convenience — it is that a size outside the scale becomes
 * unrepresentable. There are fifteen roles and no sixteenth.
 */
export type TypeRole =
  | "display-large" | "display-medium" | "display-small"
  | "headline-large" | "headline-medium" | "headline-small"
  | "title-large" | "title-medium" | "title-small"
  | "body-large" | "body-medium" | "body-small"
  | "label-large" | "label-medium" | "label-small";

type TextProps = {
  role: TypeRole;
  as?: ElementType;
  /** Vertical alignment only: table columns and axis ticks. Never a hero figure. */
  tabular?: boolean;
  className?: string;
  /** Colour and layout only. A font-size here defeats the point of the scale. */
  style?: CSSProperties;
  children: ReactNode;
};

export function Text({
  role,
  as: Tag = "p",
  tabular = false,
  className,
  style,
  children,
}: TextProps) {
  const classes = [`bb-${role}`, tabular ? "bb-tabular" : null, className]
    .filter(Boolean)
    .join(" ");
  return (
    <Tag className={classes} style={style}>
      {children}
    </Tag>
  );
}
