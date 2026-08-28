from backend.main import normalize_final_answer


def test_final_answer_preserves_all_paragraphs_and_repeated_content() -> None:
    answer = "\n\n".join(
        [
            "第一段：核实结果",
            "第二段：邮件列表",
            "第三段：准备展开详情：",
            "第四段：此前会被错误截掉",
            "第二段：邮件列表",
            "第六段：结论",
        ]
    )

    assert normalize_final_answer(f"\n{answer}\n") == answer
