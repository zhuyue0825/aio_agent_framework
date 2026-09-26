import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import MaterialComposer from "../MaterialComposer";
import RichText from "../RichText";
import { api, type Attachment, type Evidence } from "../api";

it("blocks sending while uploading and on failure, then permits retry or removal", async () => {
  vi.spyOn(api, "knowledgeBases").mockResolvedValue({knowledge_bases: []});
  vi.spyOn(api, "selectedKnowledge").mockResolvedValue({knowledge_ids: []});
  let resolve!: (a: Attachment) => void;
  vi.spyOn(api, "uploadAttachment").mockReturnValue(new Promise(r => { resolve = r; }));
  const changed = vi.fn();
  const view = render(<MaterialComposer conversationId="conv" workspace={null} busy={false} reset={0} onChange={changed}/>);
  await waitFor(() => expect(changed).toHaveBeenLastCalledWith({attachment_ids: [], knowledge_ids: []}, false));
  const file = new File(["hello"], "test.txt", {type: "text/plain"});
  await userEvent.upload(view.container.querySelector('input[type="file"]') as HTMLInputElement, file);
  expect(changed).toHaveBeenLastCalledWith({attachment_ids: [], knowledge_ids: []}, true);
  resolve({id:"a",name:"test.txt",source_kind:"upload",source_path:"",status:"FAILED",error_message:"解析失败"} as Attachment);
  await screen.findByText("解析失败");
  expect(changed).toHaveBeenLastCalledWith({attachment_ids: [], knowledge_ids: []}, true);
  vi.spyOn(api,"retryAttachment").mockResolvedValue({id:"a",name:"test.txt",source_kind:"upload",source_path:"",status:"READY"} as Attachment);
  await userEvent.click(screen.getByRole("button",{name:"重试 test.txt"}));
  await waitFor(() => expect(changed).toHaveBeenLastCalledWith({attachment_ids:["a"],knowledge_ids:[]},false));
  await userEvent.click(screen.getByRole("button",{name:"移除 test.txt"}));
  expect(changed).toHaveBeenLastCalledWith({attachment_ids:[],knowledge_ids:[]},false);
});

it("only makes a known evidence citation clickable", async () => {
  const evidence = {evidence_id:"E1",kind:"upload",attachment_id:"a",chunk_id:"s1",name:"test.txt",text:"17天",location:"第1行"} as Evidence;
  const open=vi.fn();
  render(<RichText sources={[evidence]} onSource={open}>保留17天[E1]，未知[E9]。</RichText>);
  await userEvent.click(screen.getByRole("button",{name:"E1"}));
  expect(open).toHaveBeenCalledWith(evidence);
  expect(screen.queryByRole("button",{name:"E9"})).toBeNull();
});
