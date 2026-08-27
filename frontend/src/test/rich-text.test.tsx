import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import RichText from "../RichText";

it("renders agent Markdown as safe rich text", () => {
  const { container } = render(
    <RichText>{`# 邮件摘要

**最近五天**共收到 2 封邮件。

1. 第一封
2. 第二封

| 发件人 | 状态 |
| --- | --- |
| user@example.com | 未读 |

[查看文档](https://example.com/docs)

![远程跟踪图](https://example.com/tracking.png)

<script>alert("xss")</script>`}</RichText>,
  );

  expect(screen.getByRole("heading", { name: "邮件摘要" })).toBeVisible();
  expect(screen.getByText("最近五天").tagName).toBe("STRONG");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByRole("table")).toBeVisible();

  const link = screen.getByRole("link", { name: "查看文档" });
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");

  expect(container.querySelector("script")).not.toBeInTheDocument();
  expect(container.querySelector("img")).not.toBeInTheDocument();
  expect(screen.getByText("[图片：远程跟踪图]")).toBeVisible();
});
