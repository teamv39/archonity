use tree_sitter::{Node, Parser};

fn dump(n: Node, src: &[u8], depth: usize, field: Option<&str>) {
    let p = n.start_position();
    let e = n.end_position();
    let text = if n.child_count() == 0 { format!(" {:?}", n.utf8_text(src).unwrap()) } else { String::new() };
    println!("{}{}{} [{}:{}-{}:{}]{}", "  ".repeat(depth), field.map(|f| format!("{f}: ")).unwrap_or_default(), n.kind(), p.row + 1, p.column, e.row + 1, e.column, text);
    let mut c = n.walk();
    for (i, ch) in n.children(&mut c).enumerate() {
        dump(ch, src, depth + 1, n.field_name_for_child(i as u32));
    }
}

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let src = std::fs::read(&path).unwrap();
    let mut parser = Parser::new();
    parser.set_language(&tree_sitter_java::LANGUAGE.into()).unwrap();
    let tree = parser.parse(&src, None).unwrap();
    dump(tree.root_node(), &src, 0, None);
}
