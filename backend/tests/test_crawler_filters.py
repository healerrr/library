import pytest

from app.services.crawler import (
    crawl_policy_reason,
    extract_internal_links,
    is_dynamic_product_page,
    is_dynamic_product_url,
    is_product_data_url,
    normalize_internal_link,
    product_route_matches,
    should_block_page_pruning,
)
from app.models import Site
from app.schemas import SiteCreate
from app.services.ssrf import UnsafeUrlError, validate_url_format


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
    site = SiteCreate(name="Example", domain="example.com", product_routes=["product"])
    assert site.sitemap_url == ""
    assert site.site_type == "baseline"


def test_candidate_site_type_is_supported() -> None:
    site = SiteCreate(
        name="Candidate",
        domain="candidate.example.com",
        site_type="candidate",
        product_routes=["product"],
    )
    assert site.site_type == "candidate"


def test_http_site_with_non_standard_port_is_preserved() -> None:
    site = SiteCreate(
        name="Port site",
        domain="http://spider.aikonchem.com:30045/",
        site_scheme="http",
        product_routes=["product"],
    )
    assert site.domain == "spider.aikonchem.com:30045"
    assert site.site_scheme == "http"


def test_route_rules_accept_newline_separated_input() -> None:
    site = SiteCreate(
        name="Example",
        domain="example.com",
        product_routes=["product"],
        include_patterns="^/about\n^/news",  # type: ignore[arg-type]
    )
    assert site.include_patterns == ["^/about", "^/news"]


def test_product_routes_are_required_and_accept_comma_separated_input() -> None:
    with pytest.raises(ValueError, match="product_routes"):
        SiteCreate(name="Example", domain="example.com")
    site = SiteCreate(
        name="Example",
        domain="example.com",
        product_routes="product, category,product",  # type: ignore[arg-type]
    )
    assert site.product_routes == ["product", "category"]


def policy_site(*, include: list[str] | None = None, exclude: list[str] | None = None) -> Site:
    return Site(
        name="Policy site",
        domain="example.com",
        sitemap_url="",
        site_type="baseline",
        status="active",
        product_routes=["product"],
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


def test_product_routes_match_complete_path_segments() -> None:
    assert product_route_matches("product", "/product/ABC-123")
    assert product_route_matches("category", "/en/category/reagents")
    assert product_route_matches("catalog/product", "/en/catalog/product/ABC-123")
    assert not product_route_matches("product", "/news/product-launch")
    assert not product_route_matches("product", "/products/ABC-123")


def test_crawl_policy_filters_configured_product_routes() -> None:
    site = policy_site()
    assert crawl_policy_reason("https://example.com/product/ABC-123", site) == (
        "命中产品相关路由：product"
    )
    assert crawl_policy_reason("https://example.com/news/product-launch", site) is None


def test_non_standard_port_links_stay_on_configured_endpoint() -> None:
    base_url = "http://spider.aikonchem.com:30045/"
    domains = {"spider.aikonchem.com:30045"}
    assert normalize_internal_link("/about", base_url, domains) == (
        "http://spider.aikonchem.com:30045/about"
    )
    assert normalize_internal_link(
        "http://spider.aikonchem.com:30046/about",
        base_url,
        domains,
    ) is None


def test_ssrf_validation_allows_only_configured_non_standard_port() -> None:
    domains = {"spider.aikonchem.com:30045"}
    assert validate_url_format(
        "http://spider.aikonchem.com:30045/about",
        domains,
    ) == ("spider.aikonchem.com", 30045)
    with pytest.raises(UnsafeUrlError):
        validate_url_format("http://spider.aikonchem.com:30046/about", domains)


def test_exclude_rule_reports_matching_pattern() -> None:
    site = policy_site(exclude=[r"^/member"])
    assert crawl_policy_reason("https://example.com/member/login", site) == "命中排除规则：^/member"


def test_include_rule_rejects_non_matching_route_but_keeps_homepage() -> None:
    site = policy_site(include=[r"^/(about|news)"])
    homepage = "https://example.com/"
    assert crawl_policy_reason("https://example.com/contact", site, homepage=homepage) == "不在包含规则内"
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
