/**
 * PIM Analytics Dashboard
 *
 * A comprehensive analytics dashboard for Product Information Management
 * featuring KPI widgets, charts, and actionable insights for:
 * - Digital Shelf Analytics (search rankings, buy box, pricing)
 * - Data Quality Metrics (completeness scores, gap analysis)
 * - Channel Performance (publishing status, syndication health)
 * - Product Catalog Health (inventory, active products)
 *
 * @module frappe_pim/page/pim_analytics
 */

frappe.pages['pim-analytics'].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('PIM Analytics'),
		single_column: true
	});

	// Store page reference for later use
	wrapper.page = page;
	wrapper.analytics_page = new PIMAnalyticsPage(wrapper);
};

frappe.pages['pim-analytics'].refresh = function(wrapper) {
	if (wrapper.analytics_page) {
		wrapper.analytics_page.refresh();
	}
};

/**
 * Main Analytics Page Class
 */
class PIMAnalyticsPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = wrapper.page;
		this.body = $(this.page.body);
		this.data = {};
		this.widgets = [];
		this.charts = [];

		// Default filters
		this.filters = {
			date_range: 'last_30_days',
			channel: null,
			product_family: null
		};

		this.init();
	}

	init() {
		this.setup_page_actions();
		this.setup_filters();
		this.render_layout();
		this.load_data();
	}

	/**
	 * Setup page action buttons
	 */
	setup_page_actions() {
		// Refresh button
		this.page.set_primary_action(__('Refresh'), () => {
			this.refresh();
		}, 'refresh');

		// Export button
		this.page.add_menu_item(__('Export Dashboard'), () => {
			this.export_dashboard();
		});

		// Settings button
		this.page.add_menu_item(__('Dashboard Settings'), () => {
			this.show_settings_dialog();
		});
	}

	/**
	 * Setup filter controls
	 */
	setup_filters() {
		// Date range filter
		this.page.add_field({
			fieldname: 'date_range',
			label: __('Date Range'),
			fieldtype: 'Select',
			options: [
				{ value: 'today', label: __('Today') },
				{ value: 'last_7_days', label: __('Last 7 Days') },
				{ value: 'last_30_days', label: __('Last 30 Days') },
				{ value: 'last_90_days', label: __('Last 90 Days') },
				{ value: 'this_month', label: __('This Month') },
				{ value: 'this_quarter', label: __('This Quarter') },
				{ value: 'this_year', label: __('This Year') }
			],
			default: 'last_30_days',
			change: () => {
				this.filters.date_range = this.page.fields_dict.date_range.get_value();
				this.refresh();
			}
		});

		// Channel filter
		this.page.add_field({
			fieldname: 'channel',
			label: __('Channel'),
			fieldtype: 'Link',
			options: 'Channel',
			change: () => {
				this.filters.channel = this.page.fields_dict.channel.get_value();
				this.refresh();
			}
		});

		// Product Family filter
		this.page.add_field({
			fieldname: 'product_family',
			label: __('Product Family'),
			fieldtype: 'Link',
			options: 'Product Family',
			change: () => {
				this.filters.product_family = this.page.fields_dict.product_family.get_value();
				this.refresh();
			}
		});
	}

	/**
	 * Render the main dashboard layout
	 */
	render_layout() {
		this.body.html(`
			<div class="pim-analytics-dashboard">
				<!-- Loading Indicator -->
				<div class="analytics-loading text-center py-5">
					<div class="spinner-border text-primary" role="status">
						<span class="visually-hidden">${__('Loading...')}</span>
					</div>
					<p class="mt-2 text-muted">${__('Loading analytics data...')}</p>
				</div>

				<!-- Dashboard Content (hidden initially) -->
				<div class="analytics-content" style="display: none;">
					<!-- Summary KPI Row -->
					<div class="row kpi-summary-row mb-4">
						<div class="col-md-3">
							<div class="kpi-widget" id="kpi-total-products">
								<div class="kpi-icon"><i class="fa fa-cubes"></i></div>
								<div class="kpi-content">
									<div class="kpi-value">-</div>
									<div class="kpi-label">${__('Total Products')}</div>
									<div class="kpi-trend"></div>
								</div>
							</div>
						</div>
						<div class="col-md-3">
							<div class="kpi-widget" id="kpi-avg-quality">
								<div class="kpi-icon"><i class="fa fa-check-circle"></i></div>
								<div class="kpi-content">
									<div class="kpi-value">-</div>
									<div class="kpi-label">${__('Avg Quality Score')}</div>
									<div class="kpi-trend"></div>
								</div>
							</div>
						</div>
						<div class="col-md-3">
							<div class="kpi-widget" id="kpi-channel-ready">
								<div class="kpi-icon"><i class="fa fa-rocket"></i></div>
								<div class="kpi-content">
									<div class="kpi-value">-</div>
									<div class="kpi-label">${__('Channel Ready')}</div>
									<div class="kpi-trend"></div>
								</div>
							</div>
						</div>
						<div class="col-md-3">
							<div class="kpi-widget" id="kpi-buy-box-rate">
								<div class="kpi-icon"><i class="fa fa-shopping-cart"></i></div>
								<div class="kpi-content">
									<div class="kpi-value">-</div>
									<div class="kpi-label">${__('Buy Box Rate')}</div>
									<div class="kpi-trend"></div>
								</div>
							</div>
						</div>
					</div>

					<!-- Digital Shelf Analytics Section -->
					<div class="analytics-section mb-4">
						<h5 class="section-title">
							<i class="fa fa-chart-line"></i> ${__('Digital Shelf Analytics')}
						</h5>
						<div class="row">
							<div class="col-md-4">
								<div class="analytics-card" id="card-search-rankings">
									<div class="card-header">
										<span class="card-title">${__('Search Rankings')}</span>
										<span class="card-badge badge-primary">-</span>
									</div>
									<div class="card-body">
										<div class="mini-chart" id="chart-search-rankings"></div>
										<div class="card-metrics">
											<div class="metric">
												<span class="metric-label">${__('Top 10')}</span>
												<span class="metric-value" id="metric-top10">-</span>
											</div>
											<div class="metric">
												<span class="metric-label">${__('First Page')}</span>
												<span class="metric-value" id="metric-first-page">-</span>
											</div>
										</div>
									</div>
								</div>
							</div>
							<div class="col-md-4">
								<div class="analytics-card" id="card-price-parity">
									<div class="card-header">
										<span class="card-title">${__('Price Parity')}</span>
										<span class="card-badge badge-success">-</span>
									</div>
									<div class="card-body">
										<div class="parity-gauge" id="gauge-price-parity"></div>
										<div class="card-metrics">
											<div class="metric">
												<span class="metric-label">${__('Variance')}</span>
												<span class="metric-value" id="metric-price-variance">-</span>
											</div>
											<div class="metric">
												<span class="metric-label">${__('Violations')}</span>
												<span class="metric-value" id="metric-price-violations">-</span>
											</div>
										</div>
									</div>
								</div>
							</div>
							<div class="col-md-4">
								<div class="analytics-card" id="card-content-health">
									<div class="card-header">
										<span class="card-title">${__('Content Health')}</span>
										<span class="card-badge badge-warning">-</span>
									</div>
									<div class="card-body">
										<div class="health-bars">
											<div class="health-bar">
												<span class="health-label">${__('Titles')}</span>
												<div class="progress">
													<div class="progress-bar" id="bar-titles" style="width: 0%"></div>
												</div>
												<span class="health-value" id="val-titles">-</span>
											</div>
											<div class="health-bar">
												<span class="health-label">${__('Descriptions')}</span>
												<div class="progress">
													<div class="progress-bar" id="bar-descriptions" style="width: 0%"></div>
												</div>
												<span class="health-value" id="val-descriptions">-</span>
											</div>
											<div class="health-bar">
												<span class="health-label">${__('Images')}</span>
												<div class="progress">
													<div class="progress-bar" id="bar-images" style="width: 0%"></div>
												</div>
												<span class="health-value" id="val-images">-</span>
											</div>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Data Quality Section -->
					<div class="analytics-section mb-4">
						<h5 class="section-title">
							<i class="fa fa-shield-alt"></i> ${__('Data Quality')}
						</h5>
						<div class="row">
							<div class="col-md-6">
								<div class="analytics-card tall" id="card-quality-distribution">
									<div class="card-header">
										<span class="card-title">${__('Quality Score Distribution')}</span>
									</div>
									<div class="card-body">
										<div class="chart-container" id="chart-quality-distribution"></div>
									</div>
								</div>
							</div>
							<div class="col-md-6">
								<div class="analytics-card tall" id="card-quality-gaps">
									<div class="card-header">
										<span class="card-title">${__('Top Quality Gaps')}</span>
									</div>
									<div class="card-body">
										<div class="gaps-list" id="list-quality-gaps">
											<div class="text-muted text-center py-3">${__('Loading...')}</div>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Channel Performance Section -->
					<div class="analytics-section mb-4">
						<h5 class="section-title">
							<i class="fa fa-broadcast-tower"></i> ${__('Channel Performance')}
						</h5>
						<div class="row">
							<div class="col-md-8">
								<div class="analytics-card tall" id="card-channel-status">
									<div class="card-header">
										<span class="card-title">${__('Channel Publishing Status')}</span>
									</div>
									<div class="card-body">
										<div class="chart-container" id="chart-channel-status"></div>
									</div>
								</div>
							</div>
							<div class="col-md-4">
								<div class="analytics-card tall" id="card-syndication-health">
									<div class="card-header">
										<span class="card-title">${__('Syndication Health')}</span>
									</div>
									<div class="card-body">
										<div class="syndication-stats">
											<div class="stat-item">
												<div class="stat-icon success"><i class="fa fa-check"></i></div>
												<div class="stat-content">
													<div class="stat-value" id="stat-published">-</div>
													<div class="stat-label">${__('Published')}</div>
												</div>
											</div>
											<div class="stat-item">
												<div class="stat-icon warning"><i class="fa fa-clock"></i></div>
												<div class="stat-content">
													<div class="stat-value" id="stat-pending">-</div>
													<div class="stat-label">${__('Pending')}</div>
												</div>
											</div>
											<div class="stat-item">
												<div class="stat-icon danger"><i class="fa fa-exclamation-triangle"></i></div>
												<div class="stat-content">
													<div class="stat-value" id="stat-failed">-</div>
													<div class="stat-label">${__('Failed')}</div>
												</div>
											</div>
											<div class="stat-item">
												<div class="stat-icon info"><i class="fa fa-sync"></i></div>
												<div class="stat-content">
													<div class="stat-value" id="stat-syncing">-</div>
													<div class="stat-label">${__('Syncing')}</div>
												</div>
											</div>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Alerts & Actions Section -->
					<div class="analytics-section mb-4">
						<h5 class="section-title">
							<i class="fa fa-bell"></i> ${__('Alerts & Actions')}
						</h5>
						<div class="row">
							<div class="col-md-6">
								<div class="analytics-card" id="card-recent-alerts">
									<div class="card-header">
										<span class="card-title">${__('Recent Alerts')}</span>
										<a href="#" class="card-link" id="link-all-alerts">${__('View All')}</a>
									</div>
									<div class="card-body">
										<div class="alerts-list" id="list-recent-alerts">
											<div class="text-muted text-center py-3">${__('Loading...')}</div>
										</div>
									</div>
								</div>
							</div>
							<div class="col-md-6">
								<div class="analytics-card" id="card-recommended-actions">
									<div class="card-header">
										<span class="card-title">${__('Recommended Actions')}</span>
									</div>
									<div class="card-body">
										<div class="actions-list" id="list-actions">
											<div class="text-muted text-center py-3">${__('Loading...')}</div>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<style>
				.pim-analytics-dashboard {
					padding: 15px;
				}

				/* KPI Widgets */
				.kpi-widget {
					background: var(--card-bg);
					border-radius: 8px;
					padding: 20px;
					display: flex;
					align-items: center;
					box-shadow: var(--card-shadow);
					transition: transform 0.2s, box-shadow 0.2s;
				}

				.kpi-widget:hover {
					transform: translateY(-2px);
					box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
				}

				.kpi-icon {
					width: 48px;
					height: 48px;
					border-radius: 50%;
					background: var(--primary-light);
					display: flex;
					align-items: center;
					justify-content: center;
					margin-right: 15px;
				}

				.kpi-icon i {
					font-size: 20px;
					color: var(--primary);
				}

				.kpi-value {
					font-size: 24px;
					font-weight: 600;
					color: var(--text-color);
				}

				.kpi-label {
					font-size: 12px;
					color: var(--text-muted);
					text-transform: uppercase;
				}

				.kpi-trend {
					font-size: 12px;
					margin-top: 4px;
				}

				.kpi-trend.up {
					color: var(--green-500);
				}

				.kpi-trend.down {
					color: var(--red-500);
				}

				/* Analytics Sections */
				.analytics-section {
					margin-bottom: 25px;
				}

				.section-title {
					font-size: 16px;
					font-weight: 600;
					margin-bottom: 15px;
					color: var(--text-color);
					display: flex;
					align-items: center;
					gap: 8px;
				}

				.section-title i {
					color: var(--primary);
				}

				/* Analytics Cards */
				.analytics-card {
					background: var(--card-bg);
					border-radius: 8px;
					box-shadow: var(--card-shadow);
					height: 100%;
					min-height: 200px;
				}

				.analytics-card.tall {
					min-height: 320px;
				}

				.analytics-card .card-header {
					padding: 12px 15px;
					border-bottom: 1px solid var(--border-color);
					display: flex;
					justify-content: space-between;
					align-items: center;
				}

				.analytics-card .card-title {
					font-weight: 500;
					font-size: 14px;
				}

				.analytics-card .card-badge {
					font-size: 11px;
					padding: 3px 8px;
					border-radius: 12px;
				}

				.badge-primary {
					background: var(--primary-light);
					color: var(--primary);
				}

				.badge-success {
					background: var(--green-100);
					color: var(--green-600);
				}

				.badge-warning {
					background: var(--yellow-100);
					color: var(--yellow-700);
				}

				.badge-danger {
					background: var(--red-100);
					color: var(--red-600);
				}

				.analytics-card .card-body {
					padding: 15px;
				}

				.analytics-card .card-link {
					font-size: 12px;
					color: var(--primary);
				}

				/* Card Metrics */
				.card-metrics {
					display: flex;
					gap: 20px;
					margin-top: 15px;
				}

				.metric {
					display: flex;
					flex-direction: column;
				}

				.metric-label {
					font-size: 11px;
					color: var(--text-muted);
				}

				.metric-value {
					font-size: 16px;
					font-weight: 600;
				}

				/* Health Bars */
				.health-bars {
					display: flex;
					flex-direction: column;
					gap: 12px;
				}

				.health-bar {
					display: flex;
					align-items: center;
					gap: 10px;
				}

				.health-label {
					width: 80px;
					font-size: 12px;
					color: var(--text-muted);
				}

				.health-bar .progress {
					flex: 1;
					height: 8px;
					border-radius: 4px;
					background: var(--gray-200);
				}

				.health-bar .progress-bar {
					border-radius: 4px;
					background: var(--primary);
					transition: width 0.5s ease;
				}

				.health-value {
					width: 40px;
					text-align: right;
					font-size: 12px;
					font-weight: 500;
				}

				/* Syndication Stats */
				.syndication-stats {
					display: flex;
					flex-direction: column;
					gap: 15px;
				}

				.stat-item {
					display: flex;
					align-items: center;
					gap: 12px;
				}

				.stat-icon {
					width: 36px;
					height: 36px;
					border-radius: 50%;
					display: flex;
					align-items: center;
					justify-content: center;
				}

				.stat-icon.success {
					background: var(--green-100);
					color: var(--green-600);
				}

				.stat-icon.warning {
					background: var(--yellow-100);
					color: var(--yellow-700);
				}

				.stat-icon.danger {
					background: var(--red-100);
					color: var(--red-600);
				}

				.stat-icon.info {
					background: var(--blue-100);
					color: var(--blue-600);
				}

				.stat-value {
					font-size: 18px;
					font-weight: 600;
				}

				.stat-label {
					font-size: 12px;
					color: var(--text-muted);
				}

				/* Lists */
				.gaps-list, .alerts-list, .actions-list {
					max-height: 250px;
					overflow-y: auto;
				}

				.gap-item, .alert-item, .action-item {
					padding: 10px 12px;
					border-bottom: 1px solid var(--border-color);
					display: flex;
					align-items: center;
					gap: 10px;
				}

				.gap-item:last-child, .alert-item:last-child, .action-item:last-child {
					border-bottom: none;
				}

				.gap-item:hover, .alert-item:hover, .action-item:hover {
					background: var(--gray-50);
				}

				.gap-field {
					font-weight: 500;
					flex: 1;
				}

				.gap-count {
					font-size: 12px;
					color: var(--text-muted);
				}

				.gap-severity {
					width: 8px;
					height: 8px;
					border-radius: 50%;
				}

				.gap-severity.high {
					background: var(--red-500);
				}

				.gap-severity.medium {
					background: var(--yellow-500);
				}

				.gap-severity.low {
					background: var(--green-500);
				}

				.alert-icon {
					width: 28px;
					height: 28px;
					border-radius: 50%;
					display: flex;
					align-items: center;
					justify-content: center;
					font-size: 12px;
				}

				.alert-content {
					flex: 1;
				}

				.alert-title {
					font-size: 13px;
					font-weight: 500;
				}

				.alert-time {
					font-size: 11px;
					color: var(--text-muted);
				}

				.action-item {
					cursor: pointer;
				}

				.action-icon {
					width: 32px;
					height: 32px;
					border-radius: 6px;
					background: var(--primary-light);
					display: flex;
					align-items: center;
					justify-content: center;
					color: var(--primary);
				}

				.action-title {
					font-size: 13px;
					font-weight: 500;
				}

				.action-desc {
					font-size: 11px;
					color: var(--text-muted);
				}

				/* Chart containers */
				.chart-container {
					height: 240px;
				}

				.mini-chart {
					height: 80px;
				}

				.parity-gauge {
					height: 100px;
					display: flex;
					align-items: center;
					justify-content: center;
				}

				/* Loading state */
				.analytics-loading {
					padding: 100px 0;
				}

				/* Responsive adjustments */
				@media (max-width: 768px) {
					.kpi-summary-row .col-md-3 {
						margin-bottom: 15px;
					}

					.kpi-widget {
						padding: 15px;
					}

					.kpi-value {
						font-size: 20px;
					}
				}
			</style>
		`);
	}

	/**
	 * Load all analytics data
	 */
	async load_data() {
		try {
			// Show loading state
			this.body.find('.analytics-loading').show();
			this.body.find('.analytics-content').hide();

			// Load data from multiple API endpoints in parallel
			const [
				summaryData,
				digitalShelfData,
				qualityData,
				channelData,
				alertsData
			] = await Promise.all([
				this.fetch_summary_kpis(),
				this.fetch_digital_shelf_analytics(),
				this.fetch_quality_metrics(),
				this.fetch_channel_performance(),
				this.fetch_alerts_actions()
			]);

			// Store data
			this.data = {
				summary: summaryData,
				digitalShelf: digitalShelfData,
				quality: qualityData,
				channels: channelData,
				alerts: alertsData
			};

			// Render all sections
			this.render_summary_kpis();
			this.render_digital_shelf_analytics();
			this.render_quality_metrics();
			this.render_channel_performance();
			this.render_alerts_actions();

			// Hide loading, show content
			this.body.find('.analytics-loading').hide();
			this.body.find('.analytics-content').show();

		} catch (error) {
			frappe.msgprint({
				title: __('Error Loading Analytics'),
				indicator: 'red',
				message: error.message || __('Failed to load analytics data. Please try again.')
			});
		}
	}

	/**
	 * Fetch summary KPI data
	 */
	async fetch_summary_kpis() {
		return new Promise((resolve) => {
			frappe.call({
				method: 'frappe_pim.pim.page.pim_analytics.pim_analytics.get_summary_kpis',
				args: {
					filters: this.filters
				},
				async: true,
				callback: (r) => {
					resolve(r.message || {
						total_products: 0,
						avg_quality_score: 0,
						channel_ready_count: 0,
						channel_ready_pct: 0,
						buy_box_rate: 0,
						trends: {}
					});
				},
				error: () => {
					resolve({
						total_products: 0,
						avg_quality_score: 0,
						channel_ready_count: 0,
						channel_ready_pct: 0,
						buy_box_rate: 0,
						trends: {}
					});
				}
			});
		});
	}

	/**
	 * Fetch digital shelf analytics data
	 */
	async fetch_digital_shelf_analytics() {
		return new Promise((resolve) => {
			frappe.call({
				method: 'frappe_pim.pim.page.pim_analytics.pim_analytics.get_digital_shelf_analytics',
				args: {
					filters: this.filters
				},
				async: true,
				callback: (r) => {
					resolve(r.message || {
						search_rankings: { avg_rank: 0, top_10_count: 0, first_page_count: 0, trend: [] },
						price_parity: { score: 0, variance: 0, violations: 0 },
						content_health: { titles: 0, descriptions: 0, images: 0 }
					});
				},
				error: () => {
					resolve({
						search_rankings: { avg_rank: 0, top_10_count: 0, first_page_count: 0, trend: [] },
						price_parity: { score: 0, variance: 0, violations: 0 },
						content_health: { titles: 0, descriptions: 0, images: 0 }
					});
				}
			});
		});
	}

	/**
	 * Fetch data quality metrics
	 */
	async fetch_quality_metrics() {
		return new Promise((resolve) => {
			frappe.call({
				method: 'frappe_pim.pim.page.pim_analytics.pim_analytics.get_quality_metrics',
				args: {
					filters: this.filters
				},
				async: true,
				callback: (r) => {
					resolve(r.message || {
						distribution: [],
						gaps: []
					});
				},
				error: () => {
					resolve({
						distribution: [],
						gaps: []
					});
				}
			});
		});
	}

	/**
	 * Fetch channel performance data
	 */
	async fetch_channel_performance() {
		return new Promise((resolve) => {
			frappe.call({
				method: 'frappe_pim.pim.page.pim_analytics.pim_analytics.get_channel_performance',
				args: {
					filters: this.filters
				},
				async: true,
				callback: (r) => {
					resolve(r.message || {
						channel_status: [],
						syndication: { published: 0, pending: 0, failed: 0, syncing: 0 }
					});
				},
				error: () => {
					resolve({
						channel_status: [],
						syndication: { published: 0, pending: 0, failed: 0, syncing: 0 }
					});
				}
			});
		});
	}

	/**
	 * Fetch alerts and recommended actions
	 */
	async fetch_alerts_actions() {
		return new Promise((resolve) => {
			frappe.call({
				method: 'frappe_pim.pim.page.pim_analytics.pim_analytics.get_alerts_and_actions',
				args: {
					filters: this.filters
				},
				async: true,
				callback: (r) => {
					resolve(r.message || {
						alerts: [],
						actions: []
					});
				},
				error: () => {
					resolve({
						alerts: [],
						actions: []
					});
				}
			});
		});
	}

	/**
	 * Render summary KPI widgets
	 */
	render_summary_kpis() {
		const data = this.data.summary;

		// Total Products
		this.update_kpi('kpi-total-products', {
			value: this.format_number(data.total_products),
			trend: data.trends?.products
		});

		// Average Quality Score
		this.update_kpi('kpi-avg-quality', {
			value: `${Math.round(data.avg_quality_score)}%`,
			trend: data.trends?.quality
		});

		// Channel Ready
		this.update_kpi('kpi-channel-ready', {
			value: `${data.channel_ready_pct}%`,
			subtext: `${this.format_number(data.channel_ready_count)} products`,
			trend: data.trends?.channel_ready
		});

		// Buy Box Rate
		this.update_kpi('kpi-buy-box-rate', {
			value: `${data.buy_box_rate}%`,
			trend: data.trends?.buy_box
		});
	}

	/**
	 * Update a KPI widget with new data
	 */
	update_kpi(id, data) {
		const widget = this.body.find(`#${id}`);
		widget.find('.kpi-value').text(data.value);

		if (data.subtext) {
			widget.find('.kpi-label').append(`<br><small>${data.subtext}</small>`);
		}

		if (data.trend) {
			const trendEl = widget.find('.kpi-trend');
			const trendClass = data.trend.direction === 'up' ? 'up' : 'down';
			const trendIcon = data.trend.direction === 'up' ? 'fa-arrow-up' : 'fa-arrow-down';
			trendEl.addClass(trendClass)
				.html(`<i class="fa ${trendIcon}"></i> ${data.trend.value}%`);
		}
	}

	/**
	 * Render digital shelf analytics section
	 */
	render_digital_shelf_analytics() {
		const data = this.data.digitalShelf;

		// Search Rankings
		this.body.find('#card-search-rankings .card-badge').text(`#${Math.round(data.search_rankings.avg_rank)}`);
		this.body.find('#metric-top10').text(data.search_rankings.top_10_count);
		this.body.find('#metric-first-page').text(data.search_rankings.first_page_count);

		// Render mini chart for search rankings
		if (data.search_rankings.trend && data.search_rankings.trend.length > 0) {
			this.render_sparkline('chart-search-rankings', data.search_rankings.trend);
		}

		// Price Parity
		const parityScore = data.price_parity.score;
		let parityClass = 'badge-success';
		if (parityScore < 70) parityClass = 'badge-danger';
		else if (parityScore < 85) parityClass = 'badge-warning';

		this.body.find('#card-price-parity .card-badge')
			.text(`${parityScore}%`)
			.removeClass('badge-success badge-warning badge-danger')
			.addClass(parityClass);

		this.body.find('#metric-price-variance').text(`${data.price_parity.variance}%`);
		this.body.find('#metric-price-violations').text(data.price_parity.violations);

		// Render parity gauge
		this.render_parity_gauge(parityScore);

		// Content Health
		const content = data.content_health;
		this.update_health_bar('titles', content.titles);
		this.update_health_bar('descriptions', content.descriptions);
		this.update_health_bar('images', content.images);

		// Calculate overall content score for badge
		const avgContent = Math.round((content.titles + content.descriptions + content.images) / 3);
		let contentClass = 'badge-success';
		if (avgContent < 70) contentClass = 'badge-danger';
		else if (avgContent < 85) contentClass = 'badge-warning';

		this.body.find('#card-content-health .card-badge')
			.text(`${avgContent}%`)
			.removeClass('badge-success badge-warning badge-danger')
			.addClass(contentClass);
	}

	/**
	 * Update a health bar with percentage
	 */
	update_health_bar(name, value) {
		const bar = this.body.find(`#bar-${name}`);
		const val = this.body.find(`#val-${name}`);

		bar.css('width', `${value}%`);
		val.text(`${value}%`);

		// Color based on value
		if (value >= 85) {
			bar.css('background', 'var(--green-500)');
		} else if (value >= 70) {
			bar.css('background', 'var(--yellow-500)');
		} else {
			bar.css('background', 'var(--red-500)');
		}
	}

	/**
	 * Render a simple sparkline chart
	 */
	render_sparkline(containerId, data) {
		const container = this.body.find(`#${containerId}`);
		// Simple SVG sparkline
		const width = container.width() || 200;
		const height = 60;
		const max = Math.max(...data);
		const min = Math.min(...data);
		const range = max - min || 1;

		const points = data.map((val, i) => {
			const x = (i / (data.length - 1)) * width;
			const y = height - ((val - min) / range) * height * 0.8 - height * 0.1;
			return `${x},${y}`;
		}).join(' ');

		container.html(`
			<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}">
				<polyline
					fill="none"
					stroke="var(--primary)"
					stroke-width="2"
					points="${points}"
				/>
			</svg>
		`);
	}

	/**
	 * Render price parity gauge
	 */
	render_parity_gauge(score) {
		const container = this.body.find('#gauge-price-parity');
		const color = score >= 85 ? 'var(--green-500)' : score >= 70 ? 'var(--yellow-500)' : 'var(--red-500)';

		container.html(`
			<div style="text-align: center;">
				<svg width="100" height="60" viewBox="0 0 100 60">
					<path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="var(--gray-200)" stroke-width="8"/>
					<path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="${color}" stroke-width="8"
						stroke-dasharray="${score * 1.26} 126"/>
				</svg>
				<div style="font-size: 24px; font-weight: 600; margin-top: -15px;">${score}%</div>
			</div>
		`);
	}

	/**
	 * Render quality metrics section
	 */
	render_quality_metrics() {
		const data = this.data.quality;

		// Render quality distribution chart
		this.render_quality_distribution_chart(data.distribution);

		// Render gaps list
		this.render_gaps_list(data.gaps);
	}

	/**
	 * Render quality distribution chart
	 */
	render_quality_distribution_chart(distribution) {
		const container = this.body.find('#chart-quality-distribution');

		if (!distribution || distribution.length === 0) {
			container.html(`<div class="text-muted text-center py-5">${__('No data available')}</div>`);
			return;
		}

		// Create a bar chart
		const maxCount = Math.max(...distribution.map(d => d.count));
		const html = distribution.map(d => {
			const width = (d.count / maxCount) * 100;
			const color = d.score >= 80 ? 'var(--green-500)' :
				d.score >= 60 ? 'var(--yellow-500)' : 'var(--red-500)';

			return `
				<div class="distribution-bar" style="margin-bottom: 8px;">
					<div style="display: flex; align-items: center; gap: 10px;">
						<span style="width: 60px; font-size: 12px;">${d.label}</span>
						<div style="flex: 1; height: 24px; background: var(--gray-100); border-radius: 4px; overflow: hidden;">
							<div style="width: ${width}%; height: 100%; background: ${color}; display: flex; align-items: center; padding-left: 8px;">
								<span style="color: white; font-size: 11px; font-weight: 500;">${d.count}</span>
							</div>
						</div>
					</div>
				</div>
			`;
		}).join('');

		container.html(`<div class="quality-distribution-chart">${html}</div>`);
	}

	/**
	 * Render quality gaps list
	 */
	render_gaps_list(gaps) {
		const container = this.body.find('#list-quality-gaps');

		if (!gaps || gaps.length === 0) {
			container.html(`<div class="text-muted text-center py-3">${__('No quality gaps found')}</div>`);
			return;
		}

		const html = gaps.slice(0, 10).map(gap => {
			const severityClass = gap.severity === 'high' ? 'high' :
				gap.severity === 'medium' ? 'medium' : 'low';

			return `
				<div class="gap-item">
					<div class="gap-severity ${severityClass}"></div>
					<div class="gap-field">${gap.field_name}</div>
					<div class="gap-count">${gap.missing_count} ${__('products')}</div>
				</div>
			`;
		}).join('');

		container.html(html);
	}

	/**
	 * Render channel performance section
	 */
	render_channel_performance() {
		const data = this.data.channels;

		// Render channel status chart
		this.render_channel_status_chart(data.channel_status);

		// Update syndication stats
		const synd = data.syndication;
		this.body.find('#stat-published').text(this.format_number(synd.published));
		this.body.find('#stat-pending').text(this.format_number(synd.pending));
		this.body.find('#stat-failed').text(this.format_number(synd.failed));
		this.body.find('#stat-syncing').text(this.format_number(synd.syncing));
	}

	/**
	 * Render channel status chart
	 */
	render_channel_status_chart(channelStatus) {
		const container = this.body.find('#chart-channel-status');

		if (!channelStatus || channelStatus.length === 0) {
			container.html(`<div class="text-muted text-center py-5">${__('No channel data available')}</div>`);
			return;
		}

		// Create horizontal bar chart
		const html = channelStatus.map(ch => {
			const total = ch.published + ch.pending + ch.failed;
			const pubPct = total > 0 ? (ch.published / total) * 100 : 0;
			const pendPct = total > 0 ? (ch.pending / total) * 100 : 0;
			const failPct = total > 0 ? (ch.failed / total) * 100 : 0;

			return `
				<div class="channel-status-row" style="margin-bottom: 15px;">
					<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
						<span style="font-weight: 500;">${ch.channel_name}</span>
						<span style="font-size: 12px; color: var(--text-muted);">${total} ${__('products')}</span>
					</div>
					<div style="height: 8px; background: var(--gray-100); border-radius: 4px; overflow: hidden; display: flex;">
						<div style="width: ${pubPct}%; background: var(--green-500);"></div>
						<div style="width: ${pendPct}%; background: var(--yellow-500);"></div>
						<div style="width: ${failPct}%; background: var(--red-500);"></div>
					</div>
				</div>
			`;
		}).join('');

		container.html(`
			<div class="channel-status-chart">
				${html}
				<div style="display: flex; gap: 20px; margin-top: 15px; font-size: 11px;">
					<span><span style="display: inline-block; width: 10px; height: 10px; background: var(--green-500); border-radius: 2px;"></span> ${__('Published')}</span>
					<span><span style="display: inline-block; width: 10px; height: 10px; background: var(--yellow-500); border-radius: 2px;"></span> ${__('Pending')}</span>
					<span><span style="display: inline-block; width: 10px; height: 10px; background: var(--red-500); border-radius: 2px;"></span> ${__('Failed')}</span>
				</div>
			</div>
		`);
	}

	/**
	 * Render alerts and actions section
	 */
	render_alerts_actions() {
		const data = this.data.alerts;

		// Render alerts list
		this.render_alerts_list(data.alerts);

		// Render actions list
		this.render_actions_list(data.actions);
	}

	/**
	 * Render alerts list
	 */
	render_alerts_list(alerts) {
		const container = this.body.find('#list-recent-alerts');

		if (!alerts || alerts.length === 0) {
			container.html(`<div class="text-muted text-center py-3">${__('No recent alerts')}</div>`);
			return;
		}

		const html = alerts.slice(0, 5).map(alert => {
			const iconClass = alert.type === 'error' ? 'danger' :
				alert.type === 'warning' ? 'warning' : 'info';
			const icon = alert.type === 'error' ? 'fa-exclamation-circle' :
				alert.type === 'warning' ? 'fa-exclamation-triangle' : 'fa-info-circle';

			return `
				<div class="alert-item">
					<div class="alert-icon stat-icon ${iconClass}">
						<i class="fa ${icon}"></i>
					</div>
					<div class="alert-content">
						<div class="alert-title">${alert.title}</div>
						<div class="alert-time">${alert.time_ago}</div>
					</div>
				</div>
			`;
		}).join('');

		container.html(html);
	}

	/**
	 * Render recommended actions list
	 */
	render_actions_list(actions) {
		const container = this.body.find('#list-actions');

		if (!actions || actions.length === 0) {
			container.html(`<div class="text-muted text-center py-3">${__('No recommended actions')}</div>`);
			return;
		}

		const html = actions.slice(0, 5).map(action => {
			return `
				<div class="action-item" data-action="${action.action_type}" data-params='${JSON.stringify(action.params || {})}'>
					<div class="action-icon">
						<i class="fa ${action.icon || 'fa-bolt'}"></i>
					</div>
					<div class="action-content">
						<div class="action-title">${action.title}</div>
						<div class="action-desc">${action.description}</div>
					</div>
				</div>
			`;
		}).join('');

		container.html(html);

		// Add click handlers
		container.find('.action-item').on('click', (e) => {
			const item = $(e.currentTarget);
			const actionType = item.data('action');
			const params = item.data('params');
			this.execute_action(actionType, params);
		});
	}

	/**
	 * Execute a recommended action
	 */
	execute_action(actionType, params) {
		switch (actionType) {
			case 'run_quality_scan':
				frappe.set_route('List', 'Product Master', { status: 'Draft' });
				break;
			case 'fix_gaps':
				frappe.set_route('List', 'Product Master', { completeness_score: ['<', 80] });
				break;
			case 'review_failed':
				frappe.set_route('List', 'Product Master', { sync_status: 'Failed' });
				break;
			case 'publish_pending':
				this.show_publish_dialog(params);
				break;
			default:
				frappe.msgprint(__('Action not implemented'));
		}
	}

	/**
	 * Show publish confirmation dialog
	 */
	show_publish_dialog(params) {
		frappe.confirm(
			__('Are you sure you want to publish {0} pending products?', [params.count || 0]),
			() => {
				frappe.call({
					method: 'frappe_pim.pim.api.channel.publish_to_channel',
					args: {
						channel_name: params.channel,
						product_filters: params.filters
					},
					callback: (r) => {
						if (r.message) {
							frappe.msgprint(__('Publishing job started'));
							this.refresh();
						}
					}
				});
			}
		);
	}

	/**
	 * Format a number for display
	 */
	format_number(num) {
		if (num >= 1000000) {
			return (num / 1000000).toFixed(1) + 'M';
		} else if (num >= 1000) {
			return (num / 1000).toFixed(1) + 'K';
		}
		return num.toString();
	}

	/**
	 * Refresh the dashboard
	 */
	refresh() {
		this.load_data();
	}

	/**
	 * Export dashboard data
	 */
	export_dashboard() {
		frappe.call({
			method: 'frappe_pim.pim.page.pim_analytics.pim_analytics.export_dashboard_data',
			args: {
				filters: this.filters
			},
			callback: (r) => {
				if (r.message && r.message.file_url) {
					window.open(r.message.file_url);
				}
			}
		});
	}

	/**
	 * Show settings dialog
	 */
	show_settings_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __('Dashboard Settings'),
			fields: [
				{
					fieldname: 'refresh_interval',
					label: __('Auto-refresh Interval (minutes)'),
					fieldtype: 'Int',
					default: 0,
					description: __('Set to 0 to disable auto-refresh')
				},
				{
					fieldname: 'default_channel',
					label: __('Default Channel Filter'),
					fieldtype: 'Link',
					options: 'Channel'
				},
				{
					fieldname: 'show_alerts',
					label: __('Show Alerts Section'),
					fieldtype: 'Check',
					default: 1
				}
			],
			primary_action_label: __('Save'),
			primary_action: (values) => {
				// Save settings
				frappe.call({
					method: 'frappe_pim.pim.page.pim_analytics.pim_analytics.save_dashboard_settings',
					args: {
						settings: values
					},
					callback: () => {
						dialog.hide();
						frappe.show_alert(__('Settings saved'));
					}
				});
			}
		});

		dialog.show();
	}
}
