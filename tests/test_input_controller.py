"""Tests for input controller."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestActionMapping:
    def test_load_action_map(self):
        from backend.services.gaming.input_controller import InputController, ActionMapping

        config = {
            "jump": {"type": "key_press", "key": "space"},
            "move_forward": {"type": "key_hold", "key": "w", "duration": 0.5},
            "attack": {"type": "mouse_click", "button": "left"},
        }
        result = InputController.load_action_map(config)
        assert "jump" in result
        assert result["jump"].type == "key_press"
        assert result["jump"].key == "space"
        assert result["move_forward"].type == "key_hold"
        assert result["move_forward"].duration == 0.5
        assert result["attack"].button == "left"

    def test_load_empty_map(self):
        from backend.services.gaming.input_controller import InputController
        result = InputController.load_action_map({})
        assert result == {}


class TestInputController:
    @pytest.mark.asyncio
    async def test_key_press(self):
        from backend.services.gaming.input_controller import InputController, ActionMapping

        mock_pdi = MagicMock()
        action_map = {"jump": ActionMapping(type="key_press", key="space")}
        controller = InputController(action_map)

        with patch.dict("sys.modules", {"pydirectinput": mock_pdi}):
            result = await controller.execute("jump")
            assert result["success"] is True
            mock_pdi.press.assert_called_once_with("space")

    @pytest.mark.asyncio
    async def test_key_hold(self):
        from backend.services.gaming.input_controller import InputController, ActionMapping

        mock_pdi = MagicMock()
        action_map = {"forward": ActionMapping(type="key_hold", key="w", duration=0.05)}
        controller = InputController(action_map)

        with patch.dict("sys.modules", {"pydirectinput": mock_pdi}):
            result = await controller.execute("forward")
            assert result["success"] is True
            mock_pdi.keyDown.assert_called_once_with("w")
            mock_pdi.keyUp.assert_called_once_with("w")

    @pytest.mark.asyncio
    async def test_mouse_click(self):
        from backend.services.gaming.input_controller import InputController, ActionMapping

        mock_pdi = MagicMock()
        action_map = {"attack": ActionMapping(type="mouse_click", button="left")}
        controller = InputController(action_map)

        with patch.dict("sys.modules", {"pydirectinput": mock_pdi}):
            result = await controller.execute("attack")
            assert result["success"] is True
            mock_pdi.click.assert_called_once_with(button="left")

    @pytest.mark.asyncio
    async def test_mouse_click_with_coords(self):
        from backend.services.gaming.input_controller import InputController, ActionMapping

        mock_pdi = MagicMock()
        action_map = {"click": ActionMapping(type="mouse_click", button="left")}
        controller = InputController(action_map)

        with patch.dict("sys.modules", {"pydirectinput": mock_pdi}):
            result = await controller.execute("click", {"x": 100, "y": 200})
            assert result["success"] is True
            mock_pdi.click.assert_called_once_with(100, 200, button="left")

    @pytest.mark.asyncio
    async def test_mouse_move(self):
        from backend.services.gaming.input_controller import InputController, ActionMapping

        mock_pdi = MagicMock()
        action_map = {"look": ActionMapping(type="mouse_move")}
        controller = InputController(action_map)

        with patch.dict("sys.modules", {"pydirectinput": mock_pdi}):
            result = await controller.execute("look", {"x": 50, "y": -30, "relative": True})
            assert result["success"] is True
            mock_pdi.moveRel.assert_called_once_with(50, -30)

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        from backend.services.gaming.input_controller import InputController
        controller = InputController({})
        result = await controller.execute("nonexistent_action")
        assert result["success"] is False
        assert "Unknown action" in result["error"]

    @pytest.mark.asyncio
    async def test_pydirectinput_not_installed(self):
        from backend.services.gaming.input_controller import InputController, ActionMapping

        action_map = {"jump": ActionMapping(type="key_press", key="space")}
        controller = InputController(action_map)

        with patch.dict("sys.modules", {"pydirectinput": None}):
            result = await controller.execute("jump")
            assert result["success"] is False
