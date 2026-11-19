package com.palvhs.app

import android.content.Context
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import kotlin.math.roundToInt

/** Builds controls from the same schema and visibility rules as the desktop app. */
internal class AdvancedControls(
    context: Context,
    schema: JSONArray,
    private val edit: (String, Any) -> Unit,
) : LinearLayout(context) {
    private val specs = List(schema.length()) { schema.getJSONObject(it) }
    private val groups = specs.groupBy { it.getString("group") }
    private val picker = Spinner(context)
    private val rows = LinearLayout(context).apply { orientation = VERTICAL }
    private val controls = mutableMapOf<String, Pair<View, (Any) -> Unit>>()
    private var choices = emptyList<String>()
    private var group: String? = null
    private var values = JSONObject()
    private var visibleKeys = emptySet<String>()
    private var refreshing = false

    init {
        orientation = VERTICAL
        picker.contentDescription = "Advanced settings group"
        addView(picker)
        addView(rows)
        picker.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val selected = choices.getOrNull(position)
                if (selected != group) buildGroup(selected)
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    fun refresh(state: JSONObject) {
        values = state.getJSONObject("values")
        val visible = state.getJSONArray("visible")
        visibleKeys = List(visible.length()) { visible.getString(it) }.toSet()
        val available = groups.filterValues { specs -> specs.any { it.getString("key") in visibleKeys } }.keys.toList()
        if (available != choices) {
            choices = available
            val index = group?.let(choices::indexOf)?.coerceAtLeast(0) ?: 0
            picker.adapter = ArrayAdapter(context, android.R.layout.simple_spinner_dropdown_item,
                choices.map { it.substringAfter(' ') })
            picker.setSelection(index)
            if (choices.getOrNull(index) != group) buildGroup(choices.getOrNull(index))
        }
        updateRows()
    }

    private fun buildGroup(selected: String?) {
        group = selected
        rows.removeAllViews()
        controls.clear()
        for (spec in selected?.let(groups::get).orEmpty()) {
            val key = spec.getString("key")
            val label = spec.getString("label")
            val row = LinearLayout(context).apply {
                orientation = VERTICAL
                tooltipText = spec.getString("tip").ifBlank { null }
            }
            fun change(value: Any) {
                if (!refreshing) edit(key, value)
            }
            val update: (Any) -> Unit = when (spec.getString("kind")) {
                "bool" -> {
                    val box = CheckBox(context).apply { text = label }
                    row.addView(box)
                    box.setOnCheckedChangeListener { _, checked -> change(checked) }
                    val setValue: (Any) -> Unit = { box.isChecked = it as Boolean }
                    setValue
                }
                "choice" -> {
                    row.addView(TextView(context).apply { text = label })
                    val raw = spec.getJSONArray("lo")
                    val options = List(raw.length()) { raw.getString(it) }
                    val spinner = Spinner(context).apply {
                        contentDescription = label
                        adapter = ArrayAdapter(context, android.R.layout.simple_spinner_dropdown_item, options)
                    }
                    row.addView(spinner)
                    spinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                        override fun onItemSelected(p: AdapterView<*>?, v: View?, position: Int, id: Long) {
                            val value = options[position]
                            if (value != values.optString(key)) change(value)
                        }
                        override fun onNothingSelected(p: AdapterView<*>?) {}
                    }
                    val setValue: (Any) -> Unit = {
                        val index = options.indexOf(it as String)
                        if (index >= 0 && spinner.selectedItemPosition != index) spinner.setSelection(index)
                    }
                    setValue
                }
                else -> {
                    val number = TextView(context)
                    row.addView(number)
                    val lo = spec.getDouble("lo")
                    val hi = spec.getDouble("hi")
                    val step = spec.getDouble("step")
                    val integer = spec.getString("kind") == "int"
                    val slider = SeekBar(context).apply {
                        contentDescription = label
                        max = ((hi - lo) / step).roundToInt().coerceAtLeast(1)
                    }
                    row.addView(slider)
                    slider.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                        override fun onProgressChanged(bar: SeekBar?, position: Int, fromUser: Boolean) {
                            if (fromUser) {
                                val value = (lo + position * step).coerceIn(lo, hi)
                                change(if (integer) value.roundToInt() else value)
                            }
                        }
                        override fun onStartTrackingTouch(bar: SeekBar?) {}
                        override fun onStopTrackingTouch(bar: SeekBar?) {}
                    })
                    val setValue: (Any) -> Unit = {
                        val value = (it as Number).toDouble()
                        number.text = "$label  ${if (integer) value.toInt() else String.format(Locale.ROOT, "%.4f", value).trimEnd('0').trimEnd('.')}"
                        slider.progress = ((value - lo) / step).roundToInt()
                    }
                    setValue
                }
            }
            controls[key] = row to update
            rows.addView(row)
        }
        updateRows()
    }

    private fun updateRows() {
        refreshing = true
        try {
            for ((key, control) in controls) {
                val (row, update) = control
                row.visibility = if (key in visibleKeys) View.VISIBLE else View.GONE
                values.opt(key)?.let(update)
            }
        } finally {
            refreshing = false
        }
    }
}
