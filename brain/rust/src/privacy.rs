use std::sync::OnceLock;

static RE: OnceLock<regex::Regex> = OnceLock::new();

pub fn strip_private_blocks(input: &str) -> String {
    let re = RE.get_or_init(|| {
        regex::Regex::new(r"(?is)<private>.*?</private>").expect("valid regex")
    });
    re.replace_all(input, "").into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_single_private_block() {
        let input = "keep this <private>API_KEY=sk-abc</private> keep this too";
        assert_eq!(strip_private_blocks(input), "keep this  keep this too");
    }

    #[test]
    fn strips_multiple_blocks_case_insensitive() {
        let input = "<PRIVATE>a</PRIVATE> b <private>c</private>";
        assert_eq!(strip_private_blocks(input), " b ");
    }

    #[test]
    fn preserves_content_without_tags() {
        let input = "no private data here";
        assert_eq!(strip_private_blocks(input), input);
    }

    #[test]
    fn is_multiline_safe() {
        let input = "before\n<private>\nsecret\nmultiline\n</private>\nafter";
        assert_eq!(strip_private_blocks(input), "before\n\nafter");
    }
}
