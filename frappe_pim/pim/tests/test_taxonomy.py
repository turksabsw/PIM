"""
Test Taxonomy Node hierarchy with Nested Set Model
Tests the tree structure, level calculation, path generation, and nested set operations.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestTaxonomy(FrappeTestCase):
    """Tests for Taxonomy DocType"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for all tests"""
        super().setUpClass()
        cls._cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove any test data from previous runs"""
        # Delete test taxonomy nodes first (due to foreign key)
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy Node` WHERE taxonomy LIKE 'test-%'"
        )
        # Delete test taxonomies
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy` WHERE name LIKE 'test-%'"
        )
        frappe.db.commit()

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    def _create_taxonomy(self, name="test-taxonomy", **kwargs):
        """Helper to create a test taxonomy"""
        doc = frappe.get_doc({
            "doctype": "Taxonomy",
            "taxonomy_name": kwargs.get("taxonomy_name", f"Test Taxonomy {name}"),
            "taxonomy_code": kwargs.get("taxonomy_code", name.replace("-", "_")),
            "standard": kwargs.get("standard", "Custom"),
            "max_levels": kwargs.get("max_levels", 20),
            "enabled": kwargs.get("enabled", 1),
            "code_separator": kwargs.get("code_separator", "."),
        })
        doc.insert(ignore_permissions=True)
        return doc

    def test_taxonomy_creation(self):
        """Test basic taxonomy creation"""
        taxonomy = self._create_taxonomy(name="test-create")

        self.assertTrue(taxonomy.name)
        self.assertEqual(taxonomy.taxonomy_name, "Test Taxonomy test-create")
        self.assertEqual(taxonomy.standard, "Custom")
        self.assertEqual(taxonomy.max_levels, 20)
        self.assertEqual(taxonomy.enabled, 1)

    def test_taxonomy_code_validation(self):
        """Test taxonomy code must be URL-safe slug"""
        # Valid code
        taxonomy = self._create_taxonomy(
            name="test-valid-code",
            taxonomy_code="valid_code_123"
        )
        self.assertEqual(taxonomy.taxonomy_code, "valid_code_123")

        # Invalid code with uppercase should fail
        with self.assertRaises(frappe.ValidationError):
            self._create_taxonomy(
                name="test-invalid-code",
                taxonomy_code="INVALID_CODE"
            )

    def test_taxonomy_max_levels_validation(self):
        """Test max_levels must be between 1 and 20"""
        # Valid max_levels
        taxonomy = self._create_taxonomy(
            name="test-levels-valid",
            max_levels=10
        )
        self.assertEqual(taxonomy.max_levels, 10)

        # max_levels > 20 should fail
        with self.assertRaises(frappe.ValidationError):
            self._create_taxonomy(
                name="test-levels-high",
                max_levels=25
            )

        # max_levels < 1 should fail
        with self.assertRaises(frappe.ValidationError):
            self._create_taxonomy(
                name="test-levels-low",
                max_levels=0
            )

    def test_taxonomy_unspsc_defaults(self):
        """Test UNSPSC taxonomy sets correct defaults"""
        taxonomy = self._create_taxonomy(
            name="test-unspsc",
            standard="UNSPSC"
        )

        self.assertEqual(taxonomy.max_levels, 4)
        self.assertEqual(taxonomy.level_names, "Segment,Family,Class,Commodity")
        self.assertEqual(taxonomy.node_code_pattern, r"^[0-9]{8}$")

    def test_taxonomy_gs1_defaults(self):
        """Test GS1 taxonomy sets correct defaults"""
        taxonomy = self._create_taxonomy(
            name="test-gs1",
            standard="GS1"
        )

        self.assertEqual(taxonomy.max_levels, 4)
        self.assertEqual(taxonomy.level_names, "Segment,Family,Class,Brick")

    def test_taxonomy_deletion_with_nodes(self):
        """Test taxonomy cannot be deleted when it has nodes"""
        taxonomy = self._create_taxonomy(name="test-del-nodes")

        # Create a node
        node = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": taxonomy.name,
            "node_name": "Test Node",
            "node_code": "001",
        })
        node.insert(ignore_permissions=True)

        # Try to delete taxonomy
        with self.assertRaises(frappe.ValidationError):
            taxonomy.delete()


class TestTaxonomyNode(FrappeTestCase):
    """Tests for Taxonomy Node DocType with Nested Set Model"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for all tests"""
        super().setUpClass()
        cls._cleanup_test_data()

        # Create a base taxonomy for testing
        cls.taxonomy = frappe.get_doc({
            "doctype": "Taxonomy",
            "taxonomy_name": "Test Node Taxonomy",
            "taxonomy_code": "test_node_tax",
            "standard": "Custom",
            "max_levels": 20,
            "enabled": 1,
            "code_separator": ".",
        })
        cls.taxonomy.insert(ignore_permissions=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove any test data from previous runs"""
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy Node` WHERE taxonomy LIKE 'test%'"
        )
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy` WHERE name LIKE 'test%'"
        )
        frappe.db.commit()

    def tearDown(self):
        """Clean up after each test"""
        # Delete test nodes created in this test
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy Node` WHERE taxonomy = %s",
            (self.taxonomy.name,)
        )
        frappe.db.commit()

    def _create_node(self, taxonomy=None, parent_node=None, **kwargs):
        """Helper to create a test taxonomy node"""
        taxonomy = taxonomy or self.taxonomy.name
        node_code = kwargs.get("node_code", f"N{frappe.utils.random_string(4)}")

        doc = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": taxonomy,
            "node_name": kwargs.get("node_name", f"Test Node {node_code}"),
            "node_code": node_code,
            "parent_node": parent_node,
            "enabled": kwargs.get("enabled", 1),
        })
        doc.insert(ignore_permissions=True)
        return doc

    def test_node_creation(self):
        """Test basic taxonomy node creation"""
        node = self._create_node(node_code="001", node_name="Root Node")

        self.assertTrue(node.name)
        self.assertEqual(node.node_name, "Root Node")
        self.assertEqual(node.node_code, "001")
        self.assertEqual(node.taxonomy, self.taxonomy.name)
        self.assertEqual(node.level, 1)  # Root level

    def test_node_key_generation(self):
        """Test node_key is auto-generated as {taxonomy_code}-{node_code}"""
        node = self._create_node(node_code="001", node_name="Test Key Node")

        expected_key = f"{self.taxonomy.taxonomy_code}-001"
        self.assertEqual(node.node_key, expected_key)
        self.assertEqual(node.name, expected_key)  # autoname uses node_key

    def test_level_calculation_root(self):
        """Test level is 1 for root nodes"""
        node = self._create_node(node_code="ROOT1")

        self.assertEqual(node.level, 1)
        self.assertIsNone(node.parent_node)

    def test_level_calculation_child(self):
        """Test level increments for child nodes"""
        root = self._create_node(node_code="ROOT2")
        child = self._create_node(node_code="CHILD1", parent_node=root.name)
        grandchild = self._create_node(node_code="GCHILD1", parent_node=child.name)

        self.assertEqual(root.level, 1)
        self.assertEqual(child.level, 2)
        self.assertEqual(grandchild.level, 3)

    def test_nested_set_lft_rgt(self):
        """Test Nested Set Model lft/rgt values are set correctly"""
        root = self._create_node(node_code="NSM1")

        # After insert, lft/rgt should be set
        root.reload()
        self.assertIsNotNone(root.lft)
        self.assertIsNotNone(root.rgt)
        self.assertLess(root.lft, root.rgt)

    def test_nested_set_parent_child(self):
        """Test Nested Set Model lft/rgt values for parent-child"""
        root = self._create_node(node_code="PC_ROOT")
        root.reload()

        child = self._create_node(node_code="PC_CHILD", parent_node=root.name)
        child.reload()
        root.reload()

        # Parent's lft should be less than child's lft
        self.assertLess(root.lft, child.lft)
        # Parent's rgt should be greater than child's rgt
        self.assertGreater(root.rgt, child.rgt)

    def test_nested_set_siblings(self):
        """Test Nested Set Model lft/rgt values for siblings"""
        root = self._create_node(node_code="SIB_ROOT")
        root.reload()

        child1 = self._create_node(node_code="SIB_C1", parent_node=root.name)
        child2 = self._create_node(node_code="SIB_C2", parent_node=root.name)

        child1.reload()
        child2.reload()
        root.reload()

        # Both children should be within parent's range
        self.assertGreater(child1.lft, root.lft)
        self.assertLess(child1.rgt, root.rgt)
        self.assertGreater(child2.lft, root.lft)
        self.assertLess(child2.rgt, root.rgt)

        # Children should not overlap
        self.assertTrue(
            child1.rgt < child2.lft or child2.rgt < child1.lft,
            "Sibling nodes should not overlap"
        )

    def test_is_leaf_flag(self):
        """Test is_leaf flag is set correctly"""
        root = self._create_node(node_code="LEAF1")
        root.reload()

        # Initially should be a leaf
        self.assertEqual(root.is_leaf, 1)
        self.assertEqual(root.is_group, 0)

        # Add a child
        child = self._create_node(node_code="LEAF1_C", parent_node=root.name)
        root.reload()

        # Parent should no longer be a leaf
        self.assertEqual(root.is_leaf, 0)
        self.assertEqual(root.is_group, 1)

        # Child should be a leaf
        self.assertEqual(child.is_leaf, 1)

    def test_full_path_generation(self):
        """Test full_path is generated correctly"""
        root = self._create_node(node_code="PATH1", node_name="Level1")
        child = self._create_node(
            node_code="PATH2", node_name="Level2", parent_node=root.name
        )
        grandchild = self._create_node(
            node_code="PATH3", node_name="Level3", parent_node=child.name
        )

        grandchild.reload()

        # Full path should include all ancestors
        self.assertEqual(grandchild.full_path, "Level1 > Level2 > Level3")

    def test_full_code_path_generation(self):
        """Test full_code_path is generated correctly with separator"""
        root = self._create_node(node_code="10", node_name="Root")
        child = self._create_node(node_code="20", node_name="Child", parent_node=root.name)
        grandchild = self._create_node(
            node_code="30", node_name="GChild", parent_node=child.name
        )

        grandchild.reload()

        # Code path uses taxonomy's code_separator (default ".")
        self.assertEqual(grandchild.full_code_path, "10.20.30")

    def test_max_level_validation(self):
        """Test that exceeding max_levels raises error"""
        # Create taxonomy with max 3 levels
        small_tax = frappe.get_doc({
            "doctype": "Taxonomy",
            "taxonomy_name": "Small Taxonomy",
            "taxonomy_code": "small_tax",
            "standard": "Custom",
            "max_levels": 3,
            "enabled": 1,
        })
        small_tax.insert(ignore_permissions=True)

        try:
            level1 = self._create_node(taxonomy=small_tax.name, node_code="L1")
            level2 = self._create_node(
                taxonomy=small_tax.name, node_code="L2", parent_node=level1.name
            )
            level3 = self._create_node(
                taxonomy=small_tax.name, node_code="L3", parent_node=level2.name
            )

            # Level 4 should fail (exceeds max_levels=3)
            with self.assertRaises(frappe.ValidationError):
                self._create_node(
                    taxonomy=small_tax.name, node_code="L4", parent_node=level3.name
                )
        finally:
            # Cleanup
            frappe.db.sql(
                "DELETE FROM `tabTaxonomy Node` WHERE taxonomy = %s",
                (small_tax.name,)
            )
            small_tax.delete(ignore_permissions=True)

    def test_20_level_deep_hierarchy(self):
        """Test support for 20-level deep hierarchies (spec requirement)"""
        # Create nodes up to 20 levels deep
        parent = None
        nodes = []

        for i in range(1, 21):
            node = self._create_node(
                node_code=f"D{i:02d}",
                node_name=f"Depth Level {i}",
                parent_node=parent
            )
            nodes.append(node)
            parent = node.name

        # Verify levels
        for i, node in enumerate(nodes):
            node.reload()
            self.assertEqual(node.level, i + 1)

        # Verify nested set integrity
        deepest = nodes[-1]
        deepest.reload()
        self.assertEqual(deepest.level, 20)

        # 21st level should fail (exceeds global max of 20)
        with self.assertRaises(frappe.ValidationError):
            self._create_node(
                node_code="D21",
                node_name="Depth Level 21",
                parent_node=deepest.name
            )

    def test_parent_node_same_taxonomy(self):
        """Test parent node must belong to same taxonomy"""
        # Create another taxonomy
        other_tax = frappe.get_doc({
            "doctype": "Taxonomy",
            "taxonomy_name": "Other Taxonomy",
            "taxonomy_code": "other_tax",
            "standard": "Custom",
            "enabled": 1,
        })
        other_tax.insert(ignore_permissions=True)

        try:
            other_node = self._create_node(
                taxonomy=other_tax.name, node_code="OTH1"
            )

            # Try to create node in main taxonomy with parent from other taxonomy
            with self.assertRaises(frappe.ValidationError):
                self._create_node(
                    node_code="CROSS1",
                    parent_node=other_node.name
                )
        finally:
            frappe.db.sql(
                "DELETE FROM `tabTaxonomy Node` WHERE taxonomy = %s",
                (other_tax.name,)
            )
            other_tax.delete(ignore_permissions=True)

    def test_get_children(self):
        """Test get_children method returns direct children"""
        root = self._create_node(node_code="GC_ROOT", node_name="Root")
        child1 = self._create_node(
            node_code="GC_C1", node_name="Child1", parent_node=root.name
        )
        child2 = self._create_node(
            node_code="GC_C2", node_name="Child2", parent_node=root.name
        )
        grandchild = self._create_node(
            node_code="GC_GC1", node_name="GrandChild", parent_node=child1.name
        )

        root.reload()
        children = root.get_children()

        # Should return only direct children, not grandchildren
        self.assertEqual(len(children), 2)
        child_names = [c["name"] for c in children]
        self.assertIn(child1.name, child_names)
        self.assertIn(child2.name, child_names)
        self.assertNotIn(grandchild.name, child_names)

    def test_get_descendants(self):
        """Test get_descendants method returns all descendants"""
        root = self._create_node(node_code="GD_ROOT", node_name="Root")
        child1 = self._create_node(
            node_code="GD_C1", node_name="Child1", parent_node=root.name
        )
        child2 = self._create_node(
            node_code="GD_C2", node_name="Child2", parent_node=root.name
        )
        grandchild = self._create_node(
            node_code="GD_GC1", node_name="GrandChild", parent_node=child1.name
        )

        root.reload()
        descendants = root.get_descendants()

        # Should return all descendants
        self.assertEqual(len(descendants), 3)
        self.assertIn(child1.name, descendants)
        self.assertIn(child2.name, descendants)
        self.assertIn(grandchild.name, descendants)

    def test_get_descendants_include_self(self):
        """Test get_descendants with include_self=True"""
        root = self._create_node(node_code="GDS_ROOT", node_name="Root")
        child = self._create_node(
            node_code="GDS_C1", node_name="Child", parent_node=root.name
        )

        root.reload()
        descendants = root.get_descendants(include_self=True)

        # Should include the root node itself
        self.assertEqual(len(descendants), 2)
        self.assertIn(root.name, descendants)
        self.assertIn(child.name, descendants)

    def test_get_ancestors(self):
        """Test get_ancestors method returns all ancestors"""
        root = self._create_node(node_code="GA_ROOT", node_name="Root")
        child = self._create_node(
            node_code="GA_C1", node_name="Child", parent_node=root.name
        )
        grandchild = self._create_node(
            node_code="GA_GC1", node_name="GrandChild", parent_node=child.name
        )

        grandchild.reload()
        ancestors = grandchild.get_ancestors()

        # Should return ancestors in order from root to parent
        self.assertEqual(len(ancestors), 2)
        self.assertEqual(ancestors[0].name, root.name)
        self.assertEqual(ancestors[1].name, child.name)

    def test_node_deletion_with_children(self):
        """Test node cannot be deleted when it has children"""
        root = self._create_node(node_code="DEL_ROOT", node_name="Root")
        child = self._create_node(
            node_code="DEL_C1", node_name="Child", parent_node=root.name
        )

        # Try to delete parent
        with self.assertRaises(frappe.ValidationError):
            root.delete()

    def test_children_count_update(self):
        """Test children_count is updated correctly"""
        root = self._create_node(node_code="CC_ROOT", node_name="Root")
        root.reload()
        self.assertEqual(root.children_count, 0)

        child1 = self._create_node(
            node_code="CC_C1", node_name="Child1", parent_node=root.name
        )
        root.reload()
        self.assertEqual(root.children_count, 1)

        child2 = self._create_node(
            node_code="CC_C2", node_name="Child2", parent_node=root.name
        )
        root.reload()
        self.assertEqual(root.children_count, 2)

    def test_disabled_node_filtering(self):
        """Test get_children excludes disabled nodes by default"""
        root = self._create_node(node_code="DIS_ROOT", node_name="Root")
        active_child = self._create_node(
            node_code="DIS_A", node_name="Active", parent_node=root.name, enabled=1
        )
        disabled_child = self._create_node(
            node_code="DIS_D", node_name="Disabled", parent_node=root.name, enabled=1
        )

        # Disable the child
        disabled_child.enabled = 0
        disabled_child.save(ignore_permissions=True)

        root.reload()

        # Default should exclude disabled
        children = root.get_children(include_disabled=False)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["name"], active_child.name)

        # Include disabled should return both
        children_with_disabled = root.get_children(include_disabled=True)
        self.assertEqual(len(children_with_disabled), 2)


class TestTaxonomyNodeAPI(FrappeTestCase):
    """Tests for Taxonomy Node API functions"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for all tests"""
        super().setUpClass()
        cls._cleanup_test_data()

        # Create a base taxonomy for testing
        cls.taxonomy = frappe.get_doc({
            "doctype": "Taxonomy",
            "taxonomy_name": "Test API Taxonomy",
            "taxonomy_code": "test_api_tax",
            "standard": "Custom",
            "max_levels": 10,
            "enabled": 1,
            "code_separator": ".",
        })
        cls.taxonomy.insert(ignore_permissions=True)

        # Create a tree structure for API tests
        cls.root = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": cls.taxonomy.name,
            "node_name": "API Root",
            "node_code": "API_ROOT",
            "enabled": 1,
        })
        cls.root.insert(ignore_permissions=True)
        cls.root.reload()

        cls.child1 = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": cls.taxonomy.name,
            "node_name": "API Child 1",
            "node_code": "API_C1",
            "parent_node": cls.root.name,
            "enabled": 1,
        })
        cls.child1.insert(ignore_permissions=True)

        cls.child2 = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": cls.taxonomy.name,
            "node_name": "API Child 2",
            "node_code": "API_C2",
            "parent_node": cls.root.name,
            "enabled": 1,
        })
        cls.child2.insert(ignore_permissions=True)

        cls.grandchild = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": cls.taxonomy.name,
            "node_name": "API GrandChild",
            "node_code": "API_GC1",
            "parent_node": cls.child1.name,
            "enabled": 1,
        })
        cls.grandchild.insert(ignore_permissions=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove any test data from previous runs"""
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy Node` WHERE taxonomy LIKE 'test%'"
        )
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy` WHERE name LIKE 'test%'"
        )
        frappe.db.commit()

    def test_get_node_tree_root(self):
        """Test get_node_tree returns root nodes"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import get_node_tree

        nodes = get_node_tree(taxonomy=self.taxonomy.name, parent=None)

        # Should return only root nodes
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["name"], self.root.name)
        self.assertEqual(nodes[0]["expandable"], True)  # Has children

    def test_get_node_tree_children(self):
        """Test get_node_tree returns children of a parent"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import get_node_tree

        nodes = get_node_tree(taxonomy=self.taxonomy.name, parent=self.root.name)

        # Should return children of root
        self.assertEqual(len(nodes), 2)
        node_names = [n["name"] for n in nodes]
        self.assertIn(self.child1.name, node_names)
        self.assertIn(self.child2.name, node_names)

    def test_get_node_path(self):
        """Test get_node_path returns full path information"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import get_node_path

        result = get_node_path(node_name=self.grandchild.name)

        self.assertEqual(result["node"], self.grandchild.name)
        self.assertEqual(result["taxonomy"], self.taxonomy.name)
        self.assertEqual(result["level"], 3)
        self.assertEqual(len(result["path_nodes"]), 3)

        # Check order of path nodes
        self.assertEqual(result["path_nodes"][0]["name"], self.root.name)
        self.assertEqual(result["path_nodes"][1]["name"], self.child1.name)
        self.assertEqual(result["path_nodes"][2]["name"], self.grandchild.name)

    def test_search_nodes_by_name(self):
        """Test search_nodes finds nodes by name"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import search_nodes

        results = search_nodes(
            taxonomy=self.taxonomy.name,
            search_term="Child"
        )

        # Should find both children
        self.assertGreaterEqual(len(results), 2)
        node_names = [r["node_name"] for r in results]
        self.assertTrue(any("Child" in name for name in node_names))

    def test_search_nodes_by_code(self):
        """Test search_nodes finds nodes by code"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import search_nodes

        results = search_nodes(
            taxonomy=self.taxonomy.name,
            search_term="API_C1"
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["node_code"], "API_C1")

    def test_search_nodes_min_length(self):
        """Test search_nodes requires minimum search term length"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import search_nodes

        results = search_nodes(
            taxonomy=self.taxonomy.name,
            search_term="A"  # Too short
        )

        self.assertEqual(len(results), 0)

    def test_get_leaf_nodes(self):
        """Test get_leaf_nodes returns only leaf nodes"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import get_leaf_nodes

        # Reload to ensure is_leaf is up to date
        self.child1.reload()
        self.child2.reload()
        self.grandchild.reload()

        leaves = get_leaf_nodes(taxonomy=self.taxonomy.name)

        # Should return leaf nodes (child2 and grandchild)
        leaf_names = [l["name"] for l in leaves]

        # child2 is a leaf (no children)
        self.assertIn(self.child2.name, leaf_names)
        # grandchild is a leaf
        self.assertIn(self.grandchild.name, leaf_names)
        # root is not a leaf
        self.assertNotIn(self.root.name, leaf_names)
        # child1 is not a leaf (has grandchild)
        self.assertNotIn(self.child1.name, leaf_names)

    def test_move_node(self):
        """Test move_node changes parent correctly"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import move_node

        # Create a new node for moving
        movable = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": self.taxonomy.name,
            "node_name": "Movable Node",
            "node_code": "MOVABLE",
            "parent_node": self.child1.name,
            "enabled": 1,
        })
        movable.insert(ignore_permissions=True)

        try:
            # Move to child2 as parent
            result = move_node(node_name=movable.name, new_parent=self.child2.name)

            self.assertTrue(result["success"])
            self.assertEqual(result["old_parent"], self.child1.name)
            self.assertEqual(result["new_parent"], self.child2.name)

            # Verify the move
            movable.reload()
            self.assertEqual(movable.parent_node, self.child2.name)
        finally:
            frappe.db.sql(
                "DELETE FROM `tabTaxonomy Node` WHERE name = %s",
                (movable.name,)
            )

    def test_move_node_to_self(self):
        """Test move_node prevents moving node to itself"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import move_node

        with self.assertRaises(frappe.ValidationError):
            move_node(node_name=self.child1.name, new_parent=self.child1.name)

    def test_move_node_to_descendant(self):
        """Test move_node prevents moving node to its descendant"""
        from frappe_pim.pim.doctype.taxonomy_node.taxonomy_node import move_node

        # Try to move child1 to its grandchild (circular reference)
        with self.assertRaises(frappe.ValidationError):
            move_node(node_name=self.child1.name, new_parent=self.grandchild.name)


class TestNestedSetIntegrity(FrappeTestCase):
    """Tests for verifying Nested Set Model data integrity"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        super().setUpClass()
        cls._cleanup_test_data()

        cls.taxonomy = frappe.get_doc({
            "doctype": "Taxonomy",
            "taxonomy_name": "Nested Set Test",
            "taxonomy_code": "nsm_test",
            "standard": "Custom",
            "max_levels": 10,
            "enabled": 1,
        })
        cls.taxonomy.insert(ignore_permissions=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up after tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove test data"""
        frappe.db.sql("DELETE FROM `tabTaxonomy Node` WHERE taxonomy LIKE 'nsm%'")
        frappe.db.sql("DELETE FROM `tabTaxonomy` WHERE name LIKE 'nsm%'")
        frappe.db.commit()

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.sql(
            "DELETE FROM `tabTaxonomy Node` WHERE taxonomy = %s",
            (self.taxonomy.name,)
        )
        frappe.db.commit()

    def _create_node(self, node_code, parent_node=None, node_name=None):
        """Helper to create a node"""
        doc = frappe.get_doc({
            "doctype": "Taxonomy Node",
            "taxonomy": self.taxonomy.name,
            "node_name": node_name or f"Node {node_code}",
            "node_code": node_code,
            "parent_node": parent_node,
            "enabled": 1,
        })
        doc.insert(ignore_permissions=True)
        return doc

    def test_nested_set_no_gaps(self):
        """Test lft/rgt values have no gaps in a subtree"""
        root = self._create_node("NG_ROOT")
        c1 = self._create_node("NG_C1", parent_node=root.name)
        c2 = self._create_node("NG_C2", parent_node=root.name)
        gc1 = self._create_node("NG_GC1", parent_node=c1.name)
        gc2 = self._create_node("NG_GC2", parent_node=c1.name)

        # Reload all
        for node in [root, c1, c2, gc1, gc2]:
            node.reload()

        # Collect all lft/rgt values
        values = sorted([
            root.lft, root.rgt,
            c1.lft, c1.rgt,
            c2.lft, c2.rgt,
            gc1.lft, gc1.rgt,
            gc2.lft, gc2.rgt
        ])

        # Check for consecutive values (no gaps)
        for i in range(len(values) - 1):
            self.assertEqual(
                values[i + 1] - values[i], 1,
                f"Gap found between {values[i]} and {values[i + 1]}"
            )

    def test_nested_set_no_overlaps(self):
        """Test no nodes have overlapping lft/rgt ranges"""
        root = self._create_node("NO_ROOT")
        c1 = self._create_node("NO_C1", parent_node=root.name)
        c2 = self._create_node("NO_C2", parent_node=root.name)

        for node in [root, c1, c2]:
            node.reload()

        # Siblings should not overlap
        nodes = [(c1.lft, c1.rgt), (c2.lft, c2.rgt)]

        for i, (lft1, rgt1) in enumerate(nodes):
            for j, (lft2, rgt2) in enumerate(nodes):
                if i != j:
                    # Either one should be completely before the other
                    self.assertTrue(
                        rgt1 < lft2 or rgt2 < lft1,
                        f"Overlap found: Node{i+1}({lft1},{rgt1}) Node{j+1}({lft2},{rgt2})"
                    )

    def test_nested_set_valid_tree(self):
        """Test lft < rgt for all nodes (valid tree structure)"""
        root = self._create_node("VT_ROOT")
        c1 = self._create_node("VT_C1", parent_node=root.name)
        gc1 = self._create_node("VT_GC1", parent_node=c1.name)

        # Query for invalid nodes (lft >= rgt)
        invalid = frappe.db.sql(
            """
            SELECT name, lft, rgt FROM `tabTaxonomy Node`
            WHERE taxonomy = %s AND lft >= rgt
            """,
            (self.taxonomy.name,),
            as_dict=True
        )

        self.assertEqual(len(invalid), 0, f"Found invalid nodes: {invalid}")

    def test_nested_set_parent_contains_children(self):
        """Test parent node's range contains all children's ranges"""
        root = self._create_node("PC_ROOT")
        c1 = self._create_node("PC_C1", parent_node=root.name)
        c2 = self._create_node("PC_C2", parent_node=root.name)
        gc1 = self._create_node("PC_GC1", parent_node=c1.name)

        for node in [root, c1, c2, gc1]:
            node.reload()

        # c1's children should be within c1's range
        self.assertGreater(gc1.lft, c1.lft)
        self.assertLess(gc1.rgt, c1.rgt)

        # All children should be within root's range
        for child in [c1, c2, gc1]:
            self.assertGreater(child.lft, root.lft)
            self.assertLess(child.rgt, root.rgt)
