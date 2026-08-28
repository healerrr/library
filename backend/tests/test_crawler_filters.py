from app.services.crawler import (
    crawl_policy_reason,
    extract_internal_links,
    is_dynamic_product_page,
    is_dynamic_product_url,
    is_product_data_url,
    normalize_internal_link,
    route_rule_matches,
    should_block_page_pruning,
)
from app.models import Site
from app.schemas import SiteCreate


def test_cas_product_url_is_dynamic() -> None:
    assert is_dynamic_product_url("https://www.accelsci.com/pro/1000573-03-4")
    assert is_dynamic_product_url("https://www.labgle.com/prod/100-22-1.html")


def test_regular_content_url_is_not_dynamic() -> None:
    assert not is_dynamic_product_url("https://www.labgle.com/lists.html?page=80")


def test_product_catalog_routes_are_filtered() -> None:
    assert is_product_data_url("https://www.accelsci.com/category/sulfonamides")
    assert is_product_data_url("https://www.accelsci.com/products")
    assert is_product_data_url("https://www.accelsci.com/inventory")
    assert is_product_data_url("https://www.accelsci.com/structureSearch")
    assert is_product_data_url("https://www.labgle.com/prod/index.html")
    assert not is_product_data_url("https://www.accelsci.com/about")


def test_structured_product_fields_are_dynamic() -> None:
    assert is_dynamic_product_page(
        "https://example.com/chemical-a",
        "Chemical A (1000573-03-4)",
        "CAS: 1000573-03-4. Catalog No.: A-1. Molecular Formula: C6H2BrClFI.",
    )


def test_article_that_only_mentions_cas_is_kept() -> None:
    assert not is_dynamic_product_page(
        "https://example.com/article/cas-guide",
        "CAS 1000573-03-4 使用指南",
        "介绍化学品编号的查询方法",
    )


def test_homepage_with_product_cards_is_kept() -> None:
    assert not is_dynamic_product_page(
        "https://example.com/",
        "Chemical supplier",
        "CAS: 1000573-03-4. Catalog No.: A-1. Molecular Formula: C6H2BrClFI.",
    )


def test_only_same_domain_links_are_discovered() -> None:
    html = """
    <a href="/about">About</a>
    <a href="https://friend.example.org/">友情链接</a>
    <a href="https://partner.example.com/">Partner subdomain</a>
    <a href="/pro/1000573-03-4">Product</a>
    """
    links = extract_internal_links(html, "https://www.example.com/", {"www.example.com"})
    assert "https://www.example.com/about" in links
    assert all("friend.example.org" not in link for link in links)
    assert all("partner.example.com" not in link for link in links)


def test_login_and_points_mall_routes_are_not_discovered() -> None:
    html = """
    <a href="/users/sign_in">Login</a>
    <a href="/customer/points_mall/index">Points mall</a>
    <a href="/about">About</a>
    """
    links = extract_internal_links(html, "https://example.com/", {"example.com"})
    assert links == ["https://example.com/about"]


def test_sitemap_is_optional_when_creating_site() -> None:
    site = SiteCreate(name="Example", domain="example.com")
    assert site.sitemap_url == ""
    assert site.site_type == "baseline"


def test_candidate_site_type_is_supported() -> None:
    site = SiteCreate(name="Candidate", domain="candidate.example.com", site_type="candidate")
    assert site.site_type == "candidate"


def test_simple_route_rules_are_validated_and_deduplicated() -> None:
    site = SiteCreate(
        name="Example",
        domain="example.com",
        include_patterns=[" /about ", "/about", "/news/"],
    )
    assert site.include_patterns == ["/about", "/news/"]


def test_simple_route_rule_must_start_with_slash() -> None:
    try:
        SiteCreate(name="Example", domain="example.com", include_patterns=["about"])
    except ValueError as exc:
        assert "必须以 / 开头" in str(exc)
    else:
        raise AssertionError("未拒绝缺少前导斜杠的路径规则")


def policy_site(*, include: list[str] | None = None, exclude: list[str] | None = None) -> Site:
    return Site(
        name="Policy site",
        domain="example.com",
        sitemap_url="",
        site_type="baseline",
        status="active",
        include_patterns=include or [],
        exclude_patterns=exclude or [],
        allowed_query_params=[],
        request_delay_ms=0,
        min_crawl_coverage=0.7,
    )


def test_query_parameter_whitelist_is_preserved() -> None:
    url = normalize_internal_link(
        "/news?utm_source=test&page=2&lang=zh",
        "https://example.com/",
        {"example.com"},
        {"page"},
    )
    assert url == "https://example.com/news?page=2"


def test_query_parameters_are_removed_without_whitelist() -> None:
    url = normalize_internal_link(
        "/news?page=2&utm_source=test",
        "https://example.com/",
        {"example.com"},
    )
    assert url == "https://example.com/news"


def test_exact_route_matches_only_current_page() -> None:
    assert route_rule_matches("/about", "/about")
    assert route_rule_matches("/about", "/about/")
    assert route_rule_matches("/ABOUT", "/about")
    assert not route_rule_matches("/about", "/about/team")
    assert not route_rule_matches("/about", "/about-us")


def test_directory_route_matches_page_and_descendants() -> None:
    assert route_rule_matches("/about/", "/about")
    assert route_rule_matches("/about/", "/about/")
    assert route_rule_matches("/about/", "/about/team")
    assert not route_rule_matches("/about/", "/about-us")


def test_legacy_regex_route_rule_remains_supported() -> None:
    assert route_rule_matches(r"^/(about|news)", "/news/company")
    assert route_rule_matches(r"re:^/member", "/member/login")


def test_exclude_rule_reports_matching_pattern() -> None:
    site = policy_site(exclude=[r"^/member"])
    assert crawl_policy_reason("https://example.com/member/login", site) == "命中排除路径：^/member"


def test_include_rule_rejects_non_matching_route_but_keeps_homepage() -> None:
    site = policy_site(include=[r"^/(about|news)"])
    homepage = "https://example.com/"
    assert crawl_policy_reason("https://example.com/contact", site, homepage=homepage) == "不在包含路径内"
    assert crawl_policy_reason(homepage, site, homepage=homepage) is None


def test_pruning_is_blocked_by_errors_or_low_coverage() -> None:
    assert should_block_page_pruning(
        stale_pages=4, coverage=0.9, minimum_coverage=0.7, errors=["timeout"]
    )
    assert should_block_page_pruning(
        stale_pages=4, coverage=0.5, minimum_coverage=0.7, errors=[]
    )
    assert not should_block_page_pruning(
        stale_pages=4, coverage=0.9, minimum_coverage=0.7, errors=[]
    )
    assert not should_block_page_pruning(
        stale_pages=0, coverage=0.2, minimum_coverage=0.7, errors=["timeout"]
    )
