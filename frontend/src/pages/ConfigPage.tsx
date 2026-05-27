import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getConfig, updateConfig } from '../lib/apiClient'
import { Button } from '../components/ui/button'
import { Field, FieldGroup, Label, Description, ErrorMessage } from '../components/ui/fieldset'
import { Input } from '../components/ui/input'
import { Heading } from '../components/ui/heading'
import { Text } from '../components/ui/text'
import type { Config } from '../types'

export const ConfigPage = () => {
  const queryClient = useQueryClient()
  const { data: serverCfg, isLoading } = useQuery({
    queryKey: ['config'],
    queryFn: () => getConfig().then((r) => r.data),
  })

  // Local edits layer — null means "no edits yet, fall back to serverCfg"
  const [edits, setEdits] = useState<Partial<Config> | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const form: Config | null = serverCfg ? { ...serverCfg, ...edits } : null

  const patch = (partial: Partial<Config>) => {
    setEdits((prev) => ({ ...(prev ?? {}), ...partial }))
    setSaved(false)
  }

  const setFlights = (key: 'outbound_flights' | 'return_flights', raw: string) =>
    patch({ [key]: raw.split(',').map((s) => s.trim()).filter(Boolean) })

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form) return
    setSaving(true)
    setError(null)
    try {
      await updateConfig(form)
      queryClient.invalidateQueries({ queryKey: ['config'] })
      setEdits(null)
      setSaved(true)
    } catch {
      setError('Failed to save config. Check values and try again.')
    } finally {
      setSaving(false)
    }
  }

  if (isLoading || !form) return <Text className="p-8">Loading config…</Text>

  return (
    <div className="max-w-lg mx-auto space-y-8">
      <Heading>Rules configuration</Heading>

      <form onSubmit={handleSave} className="space-y-8">
        <FieldGroup>
          <Field>
            <Label>Outbound flights (DMK→HKT)</Label>
            <Description>Comma-separated, e.g. FD3013, FD3015</Description>
            <Input
              type="text"
              value={form.outbound_flights.join(', ')}
              onChange={(e) => setFlights('outbound_flights', e.target.value)}
            />
          </Field>

          <Field>
            <Label>Return flights (HKT→DMK)</Label>
            <Description>Comma-separated</Description>
            <Input
              type="text"
              value={form.return_flights.join(', ')}
              onChange={(e) => setFlights('return_flights', e.target.value)}
            />
          </Field>

          <Field>
            <Label>Per diem rate (THB / day)</Label>
            <Input
              type="number"
              min={1}
              value={form.rate_thb_per_day}
              onChange={(e) => patch({ rate_thb_per_day: Number(e.target.value) })}
            />
          </Field>

          <Field>
            <Label>Name match threshold</Label>
            <Description>0.0 – 1.0 (default 0.8)</Description>
            <Input
              type="number"
              step="0.05"
              min={0.1}
              max={1}
              value={form.name_match_threshold}
              onChange={(e) => patch({ name_match_threshold: Number(e.target.value) })}
            />
          </Field>

          <Field>
            <Label>OCR confidence threshold</Label>
            <Description>0.0 – 1.0 (default 0.6)</Description>
            <Input
              type="number"
              step="0.05"
              min={0.1}
              max={1}
              value={form.ocr_confidence_threshold}
              onChange={(e) => patch({ ocr_confidence_threshold: Number(e.target.value) })}
            />
          </Field>
        </FieldGroup>

        {error && <ErrorMessage>{error}</ErrorMessage>}
        {saved && (
          <p className="text-green-600 dark:text-green-400 text-sm">
            Config saved. Takes effect on the next run.
          </p>
        )}

        <Button type="submit" color="blue" disabled={saving} className="w-full">
          {saving ? 'Saving…' : 'Save config'}
        </Button>
      </form>
    </div>
  )
}
